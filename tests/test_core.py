import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Database
from services.google_drive import GoogleDriveService
from services.post_builder import PostBuilder, MAX_CAPTION_LENGTH
from services.queue_manager import QueueManager


def test_text_parsing_format():
    """Verify that 1 line = 1 text and internal \\n is unescaped to actual newline."""
    sample_texts_content = """# Comment line to ignore
Утренний дайджест событий! 🔥\\nСобрали для вас самое интересное за ночь.

Аналитика за прошедшую неделю 📊\\nПодборка ключевых изменений на рынке.
Короткая подпись без переносов 🌙
"""
    lines = []
    for line in sample_texts_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed_text = line.replace(r"\n", "\n")
        lines.append(parsed_text)

    assert len(lines) == 3
    assert "\nСобрали для вас" in lines[0]
    assert "\\n" not in lines[0]
    assert "Короткая подпись без переносов 🌙" in lines[2]


def test_caption_assembly_and_length():
    """Verify combining random text with fixed footer and 1024 char limit."""
    text = "Случайный текст дня 🚀\nПодробности в закрепе."
    footer = '👉 <a href="https://t.me/channel">Подписаться</a>'
    full_caption = f"{text}\n\n{footer}"

    assert len(full_caption) <= MAX_CAPTION_LENGTH
    assert text in full_caption
    assert footer in full_caption

    # Test extreme length truncation
    huge_text = "A" * 1500
    caption = f"{huge_text}\n\n{footer}"
    if len(caption) > MAX_CAPTION_LENGTH:
        caption = caption[:MAX_CAPTION_LENGTH - 3] + "..."
    assert len(caption) == MAX_CAPTION_LENGTH
    assert caption.endswith("...")


@pytest.mark.asyncio
async def test_queue_slot_calculations():
    """Verify calculating next scheduling slots for interval and exact_times modes."""
    qm = QueueManager()

    # 1. Interval mode
    ch_interval = {
        "schedule_mode": "interval",
        "interval_minutes": 180
    }
    slots_interval = await qm.calculate_next_time_slots(ch_interval, 3)
    assert len(slots_interval) == 3
    # Check that slots are spaced ~180 minutes apart
    diff1 = (slots_interval[1] - slots_interval[0]).total_seconds() / 60
    assert abs(diff1 - 180) < 1

    # Check anchor to existing queue
    slots_after = await qm.calculate_next_time_slots(ch_interval, 2, existing_times=slots_interval)
    assert len(slots_after) == 2
    assert slots_after[0] > slots_interval[-1]
    diff2 = (slots_after[0] - slots_interval[-1]).total_seconds() / 60
    assert abs(diff2 - 180) < 1

    # 2. Exact times mode
    ch_exact = {
        "schedule_mode": "exact_times",
        "exact_times": "09:00,14:00,21:00"
    }
    slots_exact = await qm.calculate_next_time_slots(ch_exact, 3)
    assert len(slots_exact) == 3
    assert slots_exact[0] < slots_exact[1] < slots_exact[2]


@pytest.mark.asyncio
async def test_database_lifecycle(tmp_path):
    """Test SQLite database CRUD, photo tracking, and queue buffer."""
    test_db_path = str(tmp_path / "test.db")
    db = Database(test_db_path)
    await db.init_db()

    # 1. Create channel
    ch_data = {
        "channel_id": "-1001234567890",
        "title": "Тестовый канал",
        "gdrive_folder_id": "test_folder_123",
        "gdrive_texts_file_id": "test_texts_456",
        "footer_text": "<b>Подпишись!</b>",
        "photos_min": 2,
        "photos_max": 5,
        "interval_minutes": 120,
        "schedule_mode": "interval",
        "buffer_target": 3,
        "is_active": True
    }
    ch_id = await db.create_channel(ch_data)
    assert ch_id > 0

    # 2. Get channel
    ch = await db.get_channel_by_id(ch_id)
    assert ch is not None
    assert ch["title"] == "Тестовый канал"
    assert ch["buffer_target"] == 3

    # 3. Test used photos tracking and reset
    await db.mark_photos_as_used("-1001234567890", ["img1", "img2", "img3"])
    used = await db.get_used_photo_ids("-1001234567890")
    assert used == {"img1", "img2", "img3"}

    await db.reset_used_photos("-1001234567890")
    used_after = await db.get_used_photo_ids("-1001234567890")
    assert len(used_after) == 0

    # 4. Test queue management
    slot = datetime.now() + timedelta(hours=2)
    q_id = await db.add_to_queue(
        channel_id="-1001234567890",
        scheduled_time=slot,
        caption="Пост 1",
        photo_ids=["img1", "img2"],
        status="pending_local"
    )
    assert q_id > 0

    queue = await db.get_channel_queue("-1001234567890")
    assert len(queue) == 1
    assert queue[0]["photo_ids"] == ["img1", "img2"]

    # Mark as published
    await db.mark_queue_published(q_id)
    queue_after = await db.get_channel_queue("-1001234567890")
    assert len(queue_after) == 0


@pytest.mark.asyncio
async def test_post_builder_mock(tmp_path):
    """Test post builder with mocked Google Drive service."""
    from core.database import db
    db.db_path = str(tmp_path / "test_pb.db")
    await db.init_db()

    pb = PostBuilder()

    dummy_images = [
        {"id": f"img_{i}", "name": f"pic_{i}.jpg", "mimeType": "image/jpeg"}
        for i in range(10)
    ]
    dummy_texts = [
        "Текст номер 1 🔥",
        "Текст номер 2 📊\nС подробностями",
        "Текст номер 3 🌙"
    ]

    with patch("services.post_builder.gdrive_service") as mock_gdrive:
        mock_gdrive.list_images_in_folder = AsyncMock(return_value=dummy_images)
        mock_gdrive.get_texts_list = AsyncMock(return_value=dummy_texts)
        mock_gdrive.get_footer = AsyncMock(return_value="👉 <a href='https://t.me'>Ссылка</a>")

        channel = {
            "channel_id": "-100777",
            "title": "Mock Channel",
            "gdrive_folder_id": "mock_folder",
            "gdrive_texts_file_id": "mock_texts",
            "photos_min": 3,
            "photos_max": 4,
            "footer_text": ""
        }

        post = await pb.build_post(channel)

        assert post["channel_id"] == "-100777"
        assert 3 <= len(post["photo_files"]) <= 4
        assert "👉 <a href='https://t.me'>Ссылка</a>" in post["caption"]
        assert len(post["caption"]) <= MAX_CAPTION_LENGTH

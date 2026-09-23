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

    # 3. Times per day mode (4 posts per day = every 360 minutes / 6 hours)
    ch_per_day = {
        "schedule_mode": "times_per_day",
        "posts_per_day": 4
    }
    slots_per_day = await qm.calculate_next_time_slots(ch_per_day, 3)
    assert len(slots_per_day) == 3
    diff_pd = (slots_per_day[1] - slots_per_day[0]).total_seconds() / 60
    assert abs(diff_pd - 360) < 1


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
        "is_active": True
    }
    ch_id = await db.create_channel(ch_data)
    assert ch_id > 0

    # 2. Get channel
    ch = await db.get_channel_by_id(ch_id)
    assert ch is not None
    assert ch["title"] == "Тестовый канал"
    assert ch["buffer_target"] == 1

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

    # 5. Test unmark_photos and clear_channel_queue
    await db.mark_photos_as_used("-1001234567890", ["img_a", "img_b"])
    used_before = await db.get_used_photo_ids("-1001234567890")
    assert "img_a" in used_before and "img_b" in used_before

    await db.unmark_photos("-1001234567890", ["img_a"])
    used_after = await db.get_used_photo_ids("-1001234567890")
    assert "img_a" not in used_after
    assert "img_b" in used_after

    await db.add_to_queue(
        channel_id="-1001234567890",
        scheduled_time=datetime.now() + timedelta(hours=1),
        caption="Пост 2",
        photo_ids=["img_b"],
        status="pending_local"
    )
    assert len(await db.get_channel_queue("-1001234567890")) == 1
    await db.clear_channel_queue("-1001234567890")
    assert len(await db.get_channel_queue("-1001234567890")) == 0


@pytest.mark.asyncio
async def test_queue_manager_recreate_queue(tmp_path):
    """Test recreate_queue clears old pending items and refills buffer."""
    from core.database import db
    from services.queue_manager import queue_manager
    db.db_path = str(tmp_path / "test_qm_recreate.db")
    await db.init_db()

    ch_id = await db.create_channel({
        "channel_id": "-100555",
        "title": "Recreate Test",
        "gdrive_folder_id": "folder1",
        "interval_minutes": 60,
        "schedule_mode": "interval",
        "is_active": True
    })
    ch = await db.get_channel_by_id(ch_id)

    # Put a dummy post in queue
    await db.add_to_queue(
        channel_id="-100555",
        scheduled_time=datetime.now() + timedelta(hours=5),
        caption="Old Post",
        photo_ids=["old_photo_1"],
        status="pending_local"
    )
    assert len(await db.get_channel_queue("-100555")) == 1

    # Mock post_builder
    with patch("services.queue_manager.post_builder.build_post") as mock_build:
        mock_build.return_value = {
            "caption": "New Post",
            "photo_ids": ["new_photo_1"],
            "photo_files": [{"id": "new_photo_1"}],
            "raw_text": ""
        }

        # Change interval and recreate queue
        ch["interval_minutes"] = 15
        added = await queue_manager.recreate_queue(ch)

        assert added == 1
        queue = await db.get_channel_queue("-100555")
        assert len(queue) == 1
        assert all(item["caption"] == "New Post" for item in queue)


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


def test_telegram_proxy_session():
    """Verify that AiohttpSession initializes cleanly with HTTP proxy URL."""
    from aiogram.client.session.aiohttp import AiohttpSession
    proxy_url = "http://127.0.0.1:2080"
    session = AiohttpSession(proxy=proxy_url)
    assert session is not None
    assert session.proxy == proxy_url


@pytest.mark.asyncio
async def test_post_builder_small_folder_does_not_crash(tmp_path):
    """Verify that build_post gracefully handles folders with fewer images than photos_min."""
    from core.database import db
    db.db_path = str(tmp_path / "test_small_folder.db")
    await db.init_db()

    pb = PostBuilder()
    dummy_images = [{"id": "single_img_1", "name": "single.jpg"}]

    with patch("services.post_builder.gdrive_service") as mock_gdrive:
        mock_gdrive.list_images_in_folder = AsyncMock(return_value=dummy_images)
        mock_gdrive.get_texts_list = AsyncMock(return_value=["Текст 1"])
        mock_gdrive.get_footer = AsyncMock(return_value="")

        channel = {
            "channel_id": "-100888",
            "title": "Small Folder Channel",
            "gdrive_folder_id": "small_folder",
            "photos_min": 3,
            "photos_max": 5
        }

        # Should not crash with ValueError: empty range for randrange()
        post = await pb.build_post(channel)
        assert len(post["photo_files"]) == 1
        assert post["photo_ids"] == ["single_img_1"]


@pytest.mark.asyncio
async def test_post_builder_used_text_filtering(tmp_path):
    """Verify that db.get_text_hash properly filters out used texts."""
    from core.database import db
    db.db_path = str(tmp_path / "test_text_filter.db")
    await db.init_db()

    pb = PostBuilder()
    dummy_images = [{"id": f"img_{i}", "name": f"img_{i}.jpg"} for i in range(5)]
    dummy_texts = ["Text A", "Text B"]

    with patch("services.post_builder.gdrive_service") as mock_gdrive:
        mock_gdrive.list_images_in_folder = AsyncMock(return_value=dummy_images)
        mock_gdrive.get_texts_list = AsyncMock(return_value=dummy_texts)
        mock_gdrive.get_footer = AsyncMock(return_value="")

        channel = {
            "channel_id": "-100999",
            "title": "Text Filter Channel",
            "gdrive_folder_id": "fld",
            "gdrive_texts_file_id": "txt_file",
            "photos_min": 1,
            "photos_max": 2
        }

        # Mark "Text A" as used
        await db.mark_text_as_used("-100999", "Text A")

        # Now build_post MUST pick "Text B" because "Text A" is in used_text_hashes
        post = await pb.build_post(channel)
        assert post["raw_text"] == "Text B"


def test_normalize_channel_id():
    from core.utils import normalize_channel_id

    assert normalize_channel_id("https://t.me/svetasollars") == "@svetasollars"
    assert normalize_channel_id("http://t.me/svetasollars") == "@svetasollars"
    assert normalize_channel_id("https://t.me/svetasollars/") == "@svetasollars"
    assert normalize_channel_id("https://t.me/svetasollars/1234") == "@svetasollars"
    assert normalize_channel_id("https://t.me/svetasollars?boost=1") == "@svetasollars"
    assert normalize_channel_id("t.me/svetasollars") == "@svetasollars"
    assert normalize_channel_id("https://telegram.me/svetasollars") == "@svetasollars"
    assert normalize_channel_id("telegram.me/svetasollars") == "@svetasollars"
    assert normalize_channel_id("https://t.me/c/1234567890/10") == "-1001234567890"
    assert normalize_channel_id("t.me/c/1234567890") == "-1001234567890"
    assert normalize_channel_id("@svetasollars") == "@svetasollars"
    assert normalize_channel_id("svetasollars") == "@svetasollars"
    assert normalize_channel_id("-1001234567890") == "-1001234567890"
    assert normalize_channel_id("1234567890") == "1234567890"
    assert normalize_channel_id("") == ""
    assert normalize_channel_id(None) == ""


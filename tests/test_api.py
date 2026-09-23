import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.main import create_fastapi_app
from core.database import db
from webapp.api.routes import get_current_admin


@pytest.mark.asyncio
async def test_api_status_and_channels(tmp_path):
    db.db_path = str(tmp_path / "test_api.db")
    await db.init_db()

    app = create_fastapi_app()
    # Override authentication for test isolation
    app.dependency_overrides[get_current_admin] = lambda: {"id": 1, "first_name": "Test Admin"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Status check
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "google_drive" in data
        assert "publisher" in data

        # Create channel
        new_channel = {
            "channel_id": "-100999888777",
            "title": "API Test Channel",
            "gdrive_folder_id": "folder_abc",
            "gdrive_texts_file_id": "texts_xyz",
            "footer_text": "🔥 Ссылка",
            "photos_min": 2,
            "photos_max": 4,
            "interval_minutes": 180,
            "schedule_mode": "interval",
            "exact_times": "10:00,15:00",
            "is_active": True
        }
        create_res = await client.post("/api/channels", json=new_channel)
        assert create_res.status_code == 200
        ch_id = create_res.json()["id"]

        # List channels
        list_res = await client.get("/api/channels")
        assert list_res.status_code == 200
        channels = list_res.json()
        assert len(channels) == 1
        assert channels[0]["title"] == "API Test Channel"

        # Put a post in queue
        from datetime import datetime, timedelta
        await db.add_to_queue(
            channel_id="-100999888777",
            scheduled_time=datetime.now() + timedelta(hours=2),
            caption="Test Pending Post",
            photo_ids=["test_p1"],
            status="pending_local"
        )
        assert len(await db.get_channel_queue("-100999888777")) == 1

        # Update channel: change title and toggle is_active to False -> should clear queue to 0
        update_res = await client.put(f"/api/channels/{ch_id}", json={"title": "Updated Channel", "is_active": False})
        assert update_res.status_code == 200
        assert "отложка 0" in update_res.json()["message"]
        # Queue must now be completely empty (0 posts)
        assert len(await db.get_channel_queue("-100999888777")) == 0

        # Verify updated channel details
        get_res = await client.get(f"/api/channels/{ch_id}")
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Updated Channel"
        assert get_res.json()["is_active"] == 0
        assert get_res.json()["current_buffer"] == 0

        # Toggle is_active back to True
        toggle_res = await client.put(f"/api/channels/{ch_id}", json={"is_active": True})
        assert toggle_res.status_code == 200
        get_toggle = await client.get(f"/api/channels/{ch_id}")
        assert get_toggle.json()["is_active"] == 1

        # Test changing schedule interval triggers recreate_queue
        with patch("webapp.api.routes.queue_manager.recreate_queue", AsyncMock(return_value=3)) as mock_recreate:
            update_sched_res = await client.put(f"/api/channels/{ch_id}", json={"interval_minutes": 45})
            assert update_sched_res.status_code == 200
            assert mock_recreate.called

        # Test changing publication parameters (e.g. photos_min, footer_text) triggers recreate_queue
        with patch("webapp.api.routes.queue_manager.recreate_queue", AsyncMock(return_value=3)) as mock_recreate:
            update_param_res = await client.put(f"/api/channels/{ch_id}", json={"photos_min": 3, "footer_text": "Новый футер"})
            assert update_param_res.status_code == 200
            assert "Очередь пересоздана" in update_param_res.json()["message"]
            assert mock_recreate.called

        # Test manual POST /channels/{id}/recreate endpoint
        with patch("webapp.api.routes.queue_manager.recreate_queue", AsyncMock(return_value=3)) as mock_recreate:
            recreate_res = await client.post(f"/api/channels/{ch_id}/recreate")
            assert recreate_res.status_code == 200
            assert "Очередь успешно пересоздана" in recreate_res.json()["message"]
            assert mock_recreate.called

        # Test creating channel with empty title (should auto-fallback to channel_id when offline)
        auto_title_ch = {
            "channel_id": "@autotitlechannel",
            "title": "",
            "gdrive_folder_id": "folder_xyz",
            "schedule_mode": "times_per_day",
            "posts_per_day": 5
        }
        res_auto = await client.post("/api/channels", json=auto_title_ch)
        assert res_auto.status_code == 200
        auto_id = res_auto.json()["id"]
        get_auto = await client.get(f"/api/channels/{auto_id}")
        assert get_auto.status_code == 200
        assert get_auto.json()["title"] == "@autotitlechannel"
        assert get_auto.json()["posts_per_day"] == 5
        await client.delete(f"/api/channels/{auto_id}")

        # Delete channel
        del_res = await client.delete(f"/api/channels/{ch_id}")
        assert del_res.status_code == 200

        # List channels after delete
        list_after = await client.get("/api/channels")
        assert len(list_after.json()) == 0


@pytest.mark.asyncio
async def test_api_concurrent_double_trigger_protection(tmp_path):
    import asyncio
    db.db_path = str(tmp_path / "test_api_lock.db")
    await db.init_db()

    app = create_fastapi_app()
    app.dependency_overrides[get_current_admin] = lambda: {"id": 1, "first_name": "Test Admin"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create test channel
        new_channel = {
            "channel_id": "-100111222333",
            "title": "Lock Test Channel",
            "gdrive_folder_id": "folder_lock",
            "is_active": True
        }
        create_res = await client.post("/api/channels", json=new_channel)
        assert create_res.status_code == 200
        ch_id = create_res.json()["id"]

        # Simulate slow publish_post_now to test concurrent post_now calls
        slow_event = asyncio.Event()

        async def fake_publish_slow(ch):
            await slow_event.wait()

        with patch("webapp.api.routes.publisher.publish_post_now", side_effect=fake_publish_slow):
            task1 = asyncio.create_task(client.post(f"/api/channels/{ch_id}/post_now"))
            # Give task1 a moment to acquire the lock and start waiting
            await asyncio.sleep(0.02)

            # Second call while task1 is running should be rejected with 409 Conflict
            res2 = await client.post(f"/api/channels/{ch_id}/post_now")
            assert res2.status_code == 409
            assert "уже выполняется" in res2.json()["detail"]

            # Release task1
            slow_event.set()
            res1 = await task1
            assert res1.status_code == 200

        # Simulate slow recreate_queue to test concurrent recreate calls
        recreate_event = asyncio.Event()

        async def fake_recreate_slow(ch):
            await recreate_event.wait()
            return 3

        with patch("webapp.api.routes.queue_manager.recreate_queue", side_effect=fake_recreate_slow):
            task_rec1 = asyncio.create_task(client.post(f"/api/channels/{ch_id}/recreate"))
            await asyncio.sleep(0.02)

            res_rec2 = await client.post(f"/api/channels/{ch_id}/recreate")
            assert res_rec2.status_code == 409
            assert "уже выполняется" in res_rec2.json()["detail"]

            recreate_event.set()
            res_rec1 = await task_rec1
            assert res_rec1.status_code == 200


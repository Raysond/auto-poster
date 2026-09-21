import sys
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.main import create_fastapi_app
from core.database import db


@pytest.mark.asyncio
async def test_api_status_and_channels(tmp_path):
    db.db_path = str(tmp_path / "test_api.db")
    await db.init_db()

    app = create_fastapi_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Status check
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "google_drive" in data
        assert "telethon_mtproto" in data

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
            "buffer_target": 3,
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

        # Update channel
        update_res = await client.put(f"/api/channels/{ch_id}", json={"title": "Updated Channel"})
        assert update_res.status_code == 200

        # Verify updated
        get_res = await client.get(f"/api/channels/{ch_id}")
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Updated Channel"

        # Delete channel
        del_res = await client.delete(f"/api/channels/{ch_id}")
        assert del_res.status_code == 200

        # List channels after delete
        list_after = await client.get("/api/channels")
        assert len(list_after.json()) == 0

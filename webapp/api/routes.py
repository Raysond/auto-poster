import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from core.database import db
from core.config import settings
from services.google_drive import gdrive_service
from services.post_builder import post_builder
from services.publisher import publisher
from services.queue_manager import queue_manager
from services.telethon_client import telethon_service
from webapp.api.auth import validate_telegram_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# --- Pydantic Models for Request Body ---
class ChannelCreate(BaseModel):
    channel_id: str
    title: str
    gdrive_folder_id: str
    gdrive_texts_file_id: Optional[str] = ""
    gdrive_footer_file_id: Optional[str] = ""
    footer_text: Optional[str] = ""
    photos_min: int = 2
    photos_max: int = 4
    interval_minutes: int = 180
    schedule_mode: str = "interval"
    exact_times: str = "10:00,15:00,20:00"
    buffer_target: int = 3
    is_active: bool = True


class ChannelUpdate(BaseModel):
    channel_id: Optional[str] = None
    title: Optional[str] = None
    gdrive_folder_id: Optional[str] = None
    gdrive_texts_file_id: Optional[str] = None
    gdrive_footer_file_id: Optional[str] = None
    footer_text: Optional[str] = None
    photos_min: Optional[int] = None
    photos_max: Optional[int] = None
    interval_minutes: Optional[int] = None
    schedule_mode: Optional[str] = None
    exact_times: Optional[str] = None
    buffer_target: Optional[int] = None
    is_active: Optional[bool] = None


def get_current_admin(
    authorization: Optional[str] = Header(None),
    init_data_query: Optional[str] = Query(None, alias="initData")
) -> Dict[str, Any]:
    """Dependency to authenticate Telegram Mini App requests."""
    raw_data = ""
    if authorization and authorization.startswith("tma "):
        raw_data = authorization[4:]
    elif init_data_query:
        raw_data = init_data_query

    # In local testing without Telegram wrapper, allow if no tokens configured
    if not raw_data and (not settings.BOT_TOKEN or settings.BOT_TOKEN.startswith("123456789")):
        return {"id": 1, "first_name": "Local Dev"}

    return validate_telegram_init_data(raw_data)


# --- Endpoints ---

@router.get("/status")
async def get_system_status(admin: Dict[str, Any] = Depends(get_current_admin)):
    """System health check and connection status."""
    gdrive_ok, gdrive_msg = await gdrive_service.check_connection()
    telethon_authorized = await telethon_service.is_authorized()
    channels = await db.get_all_channels()

    return {
        "status": "ok",
        "google_drive": {
            "connected": gdrive_ok,
            "message": gdrive_msg
        },
        "telethon_mtproto": {
            "configured": telethon_service.is_configured(),
            "authorized": telethon_authorized,
            "mode": "native_cloud_schedule" if telethon_authorized else "bot_api_local_schedule"
        },
        "channels_count": len(channels),
        "admin": admin.get("first_name", "Admin")
    }


@router.get("/channels")
async def list_channels(admin: Dict[str, Any] = Depends(get_current_admin)):
    """List all channels with live buffer status."""
    channels = await db.get_all_channels()
    result = []
    for ch in channels:
        ch_dict = dict(ch)
        ch_dict["current_buffer"] = await queue_manager.get_current_buffer_count(ch)
        result.append(ch_dict)
    return result


@router.post("/channels")
async def create_channel(data: ChannelCreate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Add a new channel to auto-poster."""
    existing = await db.get_channel_by_telegram_id(data.channel_id)
    if existing:
        raise HTTPException(status_code=400, detail="Канал с таким ID уже существует в базе.")

    channel_id = await db.create_channel(data.model_dump())
    await db.add_log(f"Добавлен новый канал: {data.title} ({data.channel_id})", level="INFO")
    return {"id": channel_id, "message": "Канал успешно добавлен."}


@router.get("/channels/{channel_db_id}")
async def get_channel(channel_db_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Get details for a single channel."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")
    ch_dict = dict(ch)
    ch_dict["current_buffer"] = await queue_manager.get_current_buffer_count(ch)
    return ch_dict


@router.put("/channels/{channel_db_id}")
async def update_channel(
    channel_db_id: int,
    data: ChannelUpdate,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Update channel settings."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")

    update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
    await db.update_channel(channel_db_id, update_dict)
    await db.add_log(f"Обновлены настройки канала {ch['title']}", level="INFO")
    return {"message": "Настройки канала успешно сохранены."}


@router.delete("/channels/{channel_db_id}")
async def delete_channel(channel_db_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Remove a channel from auto-poster."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")

    await db.delete_channel(channel_db_id)
    await db.add_log(f"Удален канал: {ch['title']} ({ch['channel_id']})", level="WARNING")
    return {"message": "Канал успешно удален."}


@router.post("/channels/{channel_db_id}/preview")
async def preview_post(channel_db_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Generate a random post preview for testing without sending to the channel."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")

    try:
        post_data = await post_builder.build_post(ch)
        return {
            "channel_title": ch["title"],
            "caption": post_data["caption"],
            "raw_text": post_data["raw_text"],
            "footer": post_data["footer"],
            "photo_count": len(post_data["photo_files"]),
            "photos": post_data["photo_files"]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка сборки превью: {str(e)}")


@router.post("/channels/{channel_db_id}/post_now")
async def post_now(channel_db_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Publish a post immediately to the channel."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")

    try:
        await publisher.publish_post_now(ch)
        return {"message": f"Пост успешно опубликован в канал {ch['title']}!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось опубликовать пост: {str(e)}")


@router.post("/channels/{channel_db_id}/refill")
async def refill_channel_buffer(channel_db_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Force refill of the channel's 3-post buffer."""
    ch = await db.get_channel_by_id(channel_db_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден.")

    try:
        added = await queue_manager.refill_buffer(ch)
        return {"message": f"Отложка пополнена. Добавлено новых постов: {added}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка пополнения отложки: {str(e)}")


@router.get("/logs")
async def get_logs(limit: int = 50, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Get recent system activity logs."""
    logs = await db.get_logs(limit=limit)
    return logs

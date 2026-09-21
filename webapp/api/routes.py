import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Response
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


class ChannelCreate(BaseModel):
    channel_id: str
    title: Optional[str] = ""
    gdrive_folder_id: str
    gdrive_texts_file_id: Optional[str] = ""
    gdrive_footer_file_id: Optional[str] = ""
    footer_text: Optional[str] = ""
    photos_min: int = 2
    photos_max: int = 4
    interval_minutes: int = 180
    schedule_mode: str = "interval"
    exact_times: str = "10:00,15:00,20:00"
    posts_per_day: Optional[int] = 3
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
    posts_per_day: Optional[int] = None
    buffer_target: Optional[int] = None
    is_active: Optional[bool] = None


async def fetch_telegram_channel_title(channel_id: str) -> Optional[str]:
    """Fetch chat/channel title via Bot API or Telethon MTProto."""
    cleaned = str(channel_id).strip()
    target: str | int = int(cleaned) if cleaned.lstrip("-").isdigit() else cleaned

    # 1. Try via aiogram bot instance
    if publisher.bot:
        try:
            chat = await publisher.bot.get_chat(target)
            if chat and chat.title:
                return chat.title
        except Exception as e:
            logger.warning(f"Не удалось получить название канала {channel_id} через бота: {e}")

    # 2. Try via Telethon if authorized
    if await telethon_service.is_authorized():
        try:
            client = await telethon_service.get_client()
            if client:
                entity = await client.get_entity(target)
                if hasattr(entity, "title") and entity.title:
                    return entity.title
        except Exception as e:
            logger.warning(f"Не удалось получить название канала {channel_id} через Telethon: {e}")

    return None


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


@router.get("/telegram/chat-title")
async def get_telegram_chat_title(
    channel_id: str,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Fetch channel title from Telegram by channel ID or username."""
    title = await fetch_telegram_channel_title(channel_id)
    if not title:
        raise HTTPException(
            status_code=404,
            detail="Не удалось получить название канала из Telegram. Убедитесь, что бот добавлен в канал."
        )
    return {"channel_id": channel_id, "title": title}


@router.post("/channels")
async def create_channel(data: ChannelCreate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Add a new channel to auto-poster."""
    existing = await db.get_channel_by_telegram_id(data.channel_id)
    if existing:
        raise HTTPException(status_code=400, detail="Канал с таким ID уже существует в базе.")

    payload = data.model_dump()
    # Auto-fetch title from Telegram if empty
    if not payload.get("title") or not payload["title"].strip():
        fetched_title = await fetch_telegram_channel_title(data.channel_id)
        payload["title"] = fetched_title or data.channel_id

    channel_id = await db.create_channel(payload)
    await db.add_log(f"Добавлен новый канал: {payload['title']} ({data.channel_id})", level="INFO")
    return {"id": channel_id, "title": payload["title"], "message": "Канал успешно добавлен."}


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
    # If title was explicitly provided as empty string, try auto-fetching
    if "title" in update_dict and (not update_dict["title"] or not update_dict["title"].strip()):
        target_ch_id = update_dict.get("channel_id") or ch["channel_id"]
        fetched_title = await fetch_telegram_channel_title(target_ch_id)
        if fetched_title:
            update_dict["title"] = fetched_title
        else:
            del update_dict["title"]

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


@router.get("/images/{file_id}")
async def get_drive_image(file_id: str):
    """Streams an image file from Google Drive for real-time TMA preview."""
    try:
        data = await gdrive_service.download_file_bytes(file_id)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото {file_id} для превью: {e}")
        raise HTTPException(status_code=404, detail=f"Не удалось загрузить изображение: {str(e)}")


from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from core.config import settings
from core.database import db
from services.google_drive import gdrive_service
from services.queue_manager import queue_manager

router = Router()


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    if not settings.is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора.")
        return

    # Check WebApp URL
    webapp_url = settings.WEBAPP_URL.rstrip("/")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Панель управления (Mini App)",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ]
    )

    await message.answer(
        "🎛️ <b>Панель управления Auto-Poster</b>\n\n"
        "Нажмите кнопку ниже, чтобы открыть админ-панель для управления каналами, "
        "источниками Google Drive, расписанием и очередью публикаций:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    user_id = message.from_user.id
    if not settings.is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора.")
        return

    channels = await db.get_all_channels()
    gdrive_ok, gdrive_msg = await gdrive_service.check_connection()

    text = "📊 <b>Статус системы Auto-Poster:</b>\n\n"
    text += f"• <b>Google Drive API:</b> {'✅ Подключен' if gdrive_ok else '❌ Ошибка'}\n"
    text += f"  <i>({gdrive_msg})</i>\n\n"

    text += "• <b>Режим буфера:</b> ℹ️ Очередь публикаций (Telegram Bot API)\n"
    text += f"• <b>Подключенных каналов:</b> {len(channels)}\n\n"

    if channels:
        text += "<b>Каналы:</b>\n"
        for ch in channels:
            buffer_count = await queue_manager.get_current_buffer_count(ch)
            status_icon = "🟢" if ch["is_active"] else "⏸️"
            text += f"{status_icon} <b>{ch['title']}</b> ({ch['channel_id']}): {buffer_count}/{ch['buffer_target']} в отложке\n"
    else:
        text += "<i>Каналы еще не добавлены. Используйте /admin для добавления.</i>"

    await message.answer(text, parse_mode="HTML")

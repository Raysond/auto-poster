from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from core.config import settings

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if settings.is_admin(user_id):
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Вы являетесь администратором бота автопостинга.\n"
            "Чтобы открыть панель управления и настроить каналы, используйте команду /admin."
        )
    else:
        await message.answer(
            "👋 Привет! Это бот автоматической публикации контента в каналы.\n"
            "У вас нет прав администратора."
        )


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 <b>Справка по боту автопостинга:</b>\n\n"
        "• <code>/admin</code> — Открыть панель управления (Telegram Mini App)\n"
        "• <code>/status</code> — Проверить статус работы и отложки\n"
        "• <code>/help</code> — Это сообщение\n\n"
        "<i>Управление каналами, расписанием и источниками Google Drive осуществляется через панель /admin.</i>",
        parse_mode="HTML"
    )

import os
import asyncio
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from core.config import settings
from core.database import db
from bot.handlers import common, admin
from services.publisher import publisher
from services.scheduler import bot_scheduler
from services.telethon_client import telethon_service
from webapp.api.routes import router as api_router

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("auto-poster")

# Root directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent


def create_fastapi_app() -> FastAPI:
    """Builds and configures the FastAPI application."""
    app = FastAPI(title="Auto-Poster Admin TMA", docs_url="/api/docs", redoc_url=None)

    # Static files directory
    static_dir = BASE_DIR / "webapp" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Include API routes
    app.include_router(api_router)

    @app.get("/")
    async def index():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"status": "Auto-Poster Admin API is running"}

    return app


async def run_bot_polling(dp: Dispatcher, bot: Bot):
    """Run aiogram bot polling loop."""
    logger.info("Запуск Telegram Bot Polling...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка в цикле polling бота: {e}")


async def run_web_server(app: FastAPI):
    """Run uvicorn server for Telegram Mini App."""
    config = uvicorn.Config(
        app=app,
        host=settings.WEBAPP_HOST,
        port=settings.WEBAPP_PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)
    logger.info(f"Запуск Web сервера Telegram Mini App на {settings.WEBAPP_HOST}:{settings.WEBAPP_PORT}...")
    await server.serve()


async def main():
    # 1. Initialize SQLite Database
    await db.init_db()
    logger.info("База данных SQLite успешно инициализирована.")

    # 2. Check Bot Token
    if not settings.BOT_TOKEN or settings.BOT_TOKEN.startswith("123456789"):
        logger.warning(
            "⚠️ Внимание: BOT_TOKEN не задан в файле .env. "
            "Бот Telegram не сможет подключиться к сети, пока токен не будет указан."
        )

    # 3. Setup Bot & Dispatcher
    bot = None
    dp = Dispatcher()
    dp.include_router(common.router)
    dp.include_router(admin.router)

    if settings.BOT_TOKEN and not settings.BOT_TOKEN.startswith("123456789"):
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        publisher.set_bot(bot)

    # 4. Telethon check (optional MTProto)
    if telethon_service.is_configured():
        logger.info("Обнаружены учетные данные Telethon. Проверяем авторизацию MTProto...")
        if await telethon_service.is_authorized():
            logger.info("✅ Telethon MTProto авторизован. Включен режим нативной отложки Telegram!")
        else:
            logger.info("ℹ️ Telethon настроен, но сессия не авторизована. Запустите скрипт scripts/login_telethon.py для входа.")
    else:
        logger.info("ℹ️ Telethon не настроен. Работает режим локального буфера через стандартный Bot API.")

    # 5. Start background scheduler
    bot_scheduler.start()

    # 6. Create FastAPI App
    app = create_fastapi_app()

    tasks = [run_web_server(app)]
    if bot:
        tasks.append(run_bot_polling(dp, bot))

    try:
        await asyncio.gather(*tasks)
    finally:
        bot_scheduler.stop()
        if bot:
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение Auto-Poster остановлено.")

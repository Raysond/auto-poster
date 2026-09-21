"""
Утилита для однократной авторизации сессии Telethon (MTProto).
Позволяет подключить ваш аккаунт администратора канала, чтобы бот мог
отправлять посты в нативную облачную отложку Telegram (schedule_date).
"""

import asyncio
from telethon import TelegramClient
from core.config import settings


async def login():
    print("=" * 60)
    print("Авторизация Telegram MTProto Client (Telethon)")
    print("=" * 60)

    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        print("ОШИБКА: Заполните TELEGRAM_API_ID и TELEGRAM_API_HASH в файле .env!")
        print("Получить их можно на сайте https://my.telegram.org ( раздел API development tools )")
        return

    print(f"Используем API ID: {settings.TELEGRAM_API_ID}")
    print(f"Сессия будет сохранена в: {settings.TELETHON_SESSION_NAME}.session")

    client = TelegramClient(
        settings.TELETHON_SESSION_NAME,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH
    )

    await client.start()

    me = await client.get_me()
    print("\n✅ Авторизация успешно пройдена!")
    print(f"Вы вошли как: {me.first_name} (@{me.username or 'без username'}, ID: {me.id})")
    print("Теперь бот сможет планировать посты прямо в облачную отложку каналов!")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(login())

import io
import logging
from datetime import datetime
from typing import List, Tuple, Optional
from telethon import TelegramClient
from telethon.tl.types import InputMediaUploadedPhoto
from telethon.tl.functions.messages import GetScheduledMessagesRequest
from core.config import settings

logger = logging.getLogger(__name__)


class TelethonService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None

    def is_configured(self) -> bool:
        return bool(settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH)

    async def get_client(self) -> Optional[TelegramClient]:
        if not self.is_configured():
            return None

        if self.client is None:
            self.client = TelegramClient(
                settings.TELETHON_SESSION_NAME,
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH
            )

        if not self.client.is_connected():
            await self.client.connect()

        return self.client

    async def is_authorized(self) -> bool:
        """Check if Telethon user session is active and logged in."""
        if not self.is_configured():
            return False
        try:
            client = await self.get_client()
            return await client.is_user_authorized()
        except Exception as e:
            logger.warning(f"Ошибка проверки авторизации Telethon: {e}")
            return False

    async def get_native_scheduled_count(self, channel_id: str | int) -> int:
        """
        Query Telegram Cloud directly to see how many messages are currently
        waiting in the channel's native Scheduled Messages queue.
        """
        if not await self.is_authorized():
            return 0

        try:
            client = await self.get_client()
            entity = await client.get_input_entity(int(channel_id) if str(channel_id).lstrip("-").isdigit() else channel_id)
            result = await client(GetScheduledMessagesRequest(peer=entity, id=[]))
            # Grouped media messages share the same grouped_id, count unique post groups or messages
            seen_groups = set()
            count = 0
            for msg in result.messages:
                if msg.grouped_id:
                    if msg.grouped_id not in seen_groups:
                        seen_groups.add(msg.grouped_id)
                        count += 1
                else:
                    count += 1
            return count
        except Exception as e:
            logger.error(f"Ошибка получения отложенных сообщений через Telethon: {e}")
            return 0

    async def schedule_album(
        self,
        channel_id: str | int,
        photos: List[Tuple[str, bytes]],
        caption: str,
        schedule_date: datetime
    ) -> bool:
        """
        Uploads and schedules a media group (album) directly in Telegram's Cloud.
        The message will be published by Telegram even if the server is offline.
        """
        if not await self.is_authorized():
            raise RuntimeError("Telethon клиент не авторизован. Невозможно отправить в облачную отложку.")

        client = await self.get_client()
        peer = await client.get_input_entity(int(channel_id) if str(channel_id).lstrip("-").isdigit() else channel_id)

        # Upload photos as file streams
        files_to_send = []
        for name, data in photos:
            stream = io.BytesIO(data)
            stream.name = name
            files_to_send.append(stream)

        # send_file with schedule parameter places the album directly into Telegram's native schedule
        await client.send_file(
            entity=peer,
            file=files_to_send,
            caption=caption,
            parse_mode="html",
            schedule=schedule_date
        )
        logger.info(f"Успешно отправлен альбом в нативную отложку канала {channel_id} на {schedule_date}")
        return True


# Global Telethon service instance
telethon_service = TelethonService()

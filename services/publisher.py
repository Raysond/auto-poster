import io
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto
from core.database import db
from services.post_builder import post_builder

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, bot: Optional[Bot] = None):
        self.bot = bot

    def set_bot(self, bot: Bot):
        self.bot = bot

    async def publish_post_now(
        self,
        channel: Dict[str, Any],
        post_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Publishes a post to the channel immediately via Bot API.
        Used for manual 'Post Now' button or when Bot API schedule triggers.
        """
        if not self.bot:
            raise RuntimeError("Bot instance not set in Publisher.")

        channel_id = channel["channel_id"]

        # Build post if not provided
        if not post_data:
            post_data = await post_builder.build_post(channel)

        photos_data = await post_builder.download_post_images(post_data["photo_files"])
        caption = post_data["caption"]

        if not photos_data:
            raise ValueError("Нет изображений для публикации.")

        # Build InputMediaPhoto list
        media_group: List[InputMediaPhoto] = []
        for idx, (name, bdata) in enumerate(photos_data):
            file = BufferedInputFile(bdata, filename=name)
            # Caption goes strictly to the first media item
            if idx == 0:
                media_group.append(InputMediaPhoto(media=file, caption=caption, parse_mode="HTML"))
            else:
                media_group.append(InputMediaPhoto(media=file))

        try:
            target = int(channel_id) if str(channel_id).lstrip("-").isdigit() else channel_id
            if len(media_group) == 1:
                # Single photo
                await self.bot.send_photo(
                    chat_id=target,
                    photo=media_group[0].media,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                # Album of 2-10 photos
                await self.bot.send_media_group(chat_id=target, media=media_group)

            # Record in database
            await db.mark_photos_as_used(channel_id, post_data["photo_ids"])
            if post_data.get("raw_text"):
                await db.mark_text_as_used(channel_id, post_data["raw_text"])

            await db.add_log(
                f"Успешно опубликован пост в канал {channel.get('title', channel_id)} ({len(photos_data)} фото)",
                level="INFO",
                channel_id=channel_id
            )
            return True

        except Exception as e:
            err_msg = f"Ошибка публикации в канал {channel_id}: {str(e)}"
            logger.error(err_msg)
            await db.add_log(err_msg, level="ERROR", channel_id=channel_id)
            raise e


# Global publisher instance
publisher = Publisher()

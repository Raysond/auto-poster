import random
import logging
from typing import Dict, Any, List, Optional, Tuple
from core.database import db
from services.google_drive import gdrive_service

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 1024


class PostBuilder:
    async def build_post(self, channel: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds a random post candidate for the given channel:
        1. Selects random photos without recent repeats.
        2. Selects a random text line from texts.txt.
        3. Appends the fixed footer / link plate.
        """
        channel_id = str(channel["channel_id"])
        folder_id = channel.get("gdrive_folder_id")
        texts_file_id = channel.get("gdrive_texts_file_id")
        photos_min = max(1, channel.get("photos_min", 2))
        photos_max = max(photos_min, min(10, channel.get("photos_max", 4)))

        # 1. Fetch images from Google Drive
        all_images = await gdrive_service.list_images_in_folder(folder_id)
        if not all_images:
            raise ValueError(f"В папке Google Drive '{folder_id}' не найдено изображений.")

        used_photo_ids = await db.get_used_photo_ids(channel_id)
        available_images = [img for img in all_images if img["id"] not in used_photo_ids]

        # If pool of unused photos is exhausted, reset used photos
        if len(available_images) < photos_min:
            logger.info(f"Пул фото для канала {channel_id} исчерпан. Сбрасываем историю использованных фото.")
            await db.reset_used_photos(channel_id)
            available_images = all_images

        # Pick random count between min and max
        count = random.randint(photos_min, min(photos_max, len(available_images)))
        selected_images = random.sample(available_images, count)

        # 2. Fetch and pick random text
        selected_text = ""
        if texts_file_id:
            all_texts = await gdrive_service.get_texts_list(texts_file_id)
            if all_texts:
                used_text_hashes = await db.get_used_text_hashes(channel_id)
                # Map texts to their hashes
                available_texts = [
                    t for t in all_texts 
                    if db.get_text_hash(t) not in used_text_hashes
                ] if hasattr(db, "get_text_hash") else all_texts

                if not available_texts:
                    logger.info(f"Все тексты для канала {channel_id} использованы. Сбрасываем историю.")
                    await db.reset_used_texts(channel_id)
                    available_texts = all_texts

                selected_text = random.choice(available_texts)

        # 3. Get fixed footer / link plate
        footer = await gdrive_service.get_footer(channel)

        # 4. Assemble caption (respecting Telegram's 1024 char limit for media captions)
        separator = "\n\n" if (selected_text and footer) else ""
        combined_len = len(selected_text) + len(separator) + len(footer)
        if combined_len > MAX_CAPTION_LENGTH:
            allowed_text_len = MAX_CAPTION_LENGTH - len(separator) - len(footer)
            if allowed_text_len > 3:
                selected_text = selected_text[:allowed_text_len - 3] + "..."
            else:
                selected_text = ""
                separator = ""

        if selected_text and footer:
            full_caption = f"{selected_text}{separator}{footer}"
        elif selected_text:
            full_caption = selected_text
        elif footer:
            full_caption = footer
        else:
            full_caption = ""

        if len(full_caption) > MAX_CAPTION_LENGTH:
            full_caption = full_caption[:MAX_CAPTION_LENGTH - 3] + "..."

        return {
            "channel_id": channel_id,
            "caption": full_caption,
            "raw_text": selected_text,
            "footer": footer,
            "photo_files": selected_images,
            "photo_ids": [img["id"] for img in selected_images]
        }

    async def download_post_images(self, photo_files: List[Dict[str, Any]]) -> List[Tuple[str, bytes]]:
        """
        Download binary buffers for the selected images.
        Returns list of tuples: (filename, bytes).
        """
        results = []
        for img in photo_files:
            file_id = img["id"]
            name = img.get("name", f"photo_{file_id}.jpg")
            data = await gdrive_service.download_file_bytes(file_id)
            results.append((name, data))
        return results


# Global post builder instance
post_builder = PostBuilder()

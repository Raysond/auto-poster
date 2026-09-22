import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from core.database import db
from services.queue_manager import queue_manager
from services.publisher import publisher

logger = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    def start(self):
        """Start the background scheduler."""
        # Check and refill buffer every 30 seconds
        self.scheduler.add_job(
            self.job_check_queues,
            trigger=IntervalTrigger(seconds=30),
            id="job_check_queues",
            name="Проверка и пополнение буфера отложки",
            replace_existing=True
        )

        # Check local queue every 30 seconds for Bot API publishing
        self.scheduler.add_job(
            self.job_process_local_queue,
            trigger=IntervalTrigger(seconds=30),
            id="job_process_local_queue",
            name="Публикация созревших постов из локальной очереди",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("Фоновый планировщик задач запущен.")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Фоновый планировщик задач остановлен.")

    async def job_check_queues(self):
        """Periodically ensures every channel has 3 posts in queue."""
        logger.debug("Запуск плановой проверки буферов отложки...")
        try:
            await queue_manager.check_and_refill_all_active_channels()
        except Exception as e:
            logger.error(f"Ошибка в job_check_queues: {e}")

    async def job_process_local_queue(self):
        """
        Publishes posts from the local SQLite queue whose scheduled_time has arrived.
        """
        now_iso = datetime.now().isoformat()
        channels = await db.get_active_channels()

        for ch in channels:
            channel_id = str(ch["channel_id"])
            queue = await db.get_channel_queue(channel_id)
            for item in queue:
                # Check if item is ready to publish
                if item["scheduled_time"] <= now_iso and item["status"] == "pending_local":
                    try:
                        logger.info(f"Наступило время публикации для канала {channel_id}: {item['id']}")
                        # Convert item back to post_data format
                        post_data = {
                            "channel_id": channel_id,
                            "caption": item["caption"],
                            "photo_files": [{"id": pid} for pid in item["photo_ids"]],
                            "photo_ids": item["photo_ids"],
                            "raw_text": ""
                        }
                        await publisher.publish_post_now(ch, post_data)
                        await db.mark_queue_published(item["id"])
                        # Immediately top up buffer to maintain continuous cadence
                        try:
                            await queue_manager.refill_buffer(ch)
                        except Exception as ref_err:
                            logger.error(f"Ошибка пополнения буфера канала {channel_id} после публикации: {ref_err}")
                    except Exception as e:
                        logger.error(f"Ошибка публикации отложенного поста {item['id']}: {e}")
                        await db.mark_queue_failed(item["id"])
                        await db.add_log(
                            f"Пост {item['id']} снят с публикации из-за ошибки: {str(e)}",
                            level="ERROR",
                            channel_id=channel_id
                        )
                        break


# Global scheduler instance
bot_scheduler = BotScheduler()

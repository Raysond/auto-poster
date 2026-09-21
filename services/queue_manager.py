import logging
from datetime import datetime, timedelta, time
from typing import Dict, Any, List, Optional
from core.database import db
from services.post_builder import post_builder
from services.publisher import publisher
from services.telethon_client import telethon_service

logger = logging.getLogger(__name__)


class QueueManager:
    async def get_current_buffer_count(self, channel: Dict[str, Any]) -> int:
        """
        Returns the number of scheduled posts currently waiting in queue.
        If Telethon is authorized, checks Telegram Cloud native schedule.
        Otherwise checks SQLite local queue.
        """
        channel_id = str(channel["channel_id"])
        if await telethon_service.is_authorized():
            return await telethon_service.get_native_scheduled_count(channel_id)

        queue = await db.get_channel_queue(channel_id)
        return len(queue)

    def calculate_next_time_slots(self, channel: Dict[str, Any], count_needed: int) -> List[datetime]:
        """
        Calculates the next datetime slots for scheduling.
        Supports both 'interval' mode (e.g. every 3 hours) and 'exact_times' mode (e.g. 10:00, 15:00, 20:00).
        """
        now = datetime.now()
        mode = channel.get("schedule_mode", "interval")
        slots: List[datetime] = []

        if mode == "exact_times":
            times_str = channel.get("exact_times", "10:00,15:00,20:00")
            parsed_times = []
            for t_str in times_str.split(","):
                t_str = t_str.strip()
                if ":" in t_str:
                    try:
                        h, m = map(int, t_str.split(":"))
                        parsed_times.append(time(hour=h, minute=m))
                    except ValueError:
                        continue
            parsed_times.sort()

            if not parsed_times:
                parsed_times = [time(hour=10, minute=0), time(hour=15, minute=0), time(hour=20, minute=0)]

            # Find upcoming occurrences starting from now
            current_day = now.date()
            while len(slots) < count_needed:
                for t in parsed_times:
                    candidate = datetime.combine(current_day, t)
                    # Must be at least 5 minutes in the future
                    if candidate > now + timedelta(minutes=5):
                        slots.append(candidate)
                        if len(slots) == count_needed:
                            break
                current_day += timedelta(days=1)

        else:
            # Interval mode (minutes)
            interval = max(5, channel.get("interval_minutes", 180))
            # Start from now + interval
            last_time = now
            for _ in range(count_needed):
                last_time = last_time + timedelta(minutes=interval)
                slots.append(last_time)

        return slots

    async def refill_buffer(self, channel: Dict[str, Any]) -> int:
        """
        Ensures the channel has target buffer posts (default 3) in schedule.
        Returns number of newly scheduled posts.
        """
        channel_id = str(channel["channel_id"])
        target = channel.get("buffer_target", 3)
        current_count = await self.get_current_buffer_count(channel)

        needed = max(0, target - current_count)
        if needed == 0:
            return 0

        logger.info(f"Канал {channel.get('title', channel_id)}: в очереди {current_count}/{target}, пополняем на {needed} постов.")
        slots = self.calculate_next_time_slots(channel, needed)
        scheduled_count = 0

        is_mtproto = await telethon_service.is_authorized()

        for slot in slots:
            try:
                post_data = await post_builder.build_post(channel)
                if is_mtproto:
                    # Native Telegram Cloud scheduling
                    await publisher.schedule_post_native(channel, schedule_date=slot, post_data=post_data)
                else:
                    # Pre-buffer in local database
                    await db.add_to_queue(
                        channel_id=channel_id,
                        scheduled_time=slot,
                        caption=post_data["caption"],
                        photo_ids=post_data["photo_ids"],
                        status="pending_local"
                    )
                scheduled_count += 1
            except Exception as e:
                logger.error(f"Не удалось подготовить пост для канала {channel_id} на {slot}: {e}")
                await db.add_log(f"Ошибка пополнения отложки: {str(e)}", level="ERROR", channel_id=channel_id)
                break

        return scheduled_count

    async def check_and_refill_all_active_channels(self):
        """Iterates over all active channels and tops up their queues."""
        channels = await db.get_active_channels()
        for ch in channels:
            try:
                await self.refill_buffer(ch)
            except Exception as e:
                logger.error(f"Ошибка проверки отложки канала {ch.get('title', ch.get('channel_id'))}: {e}")


# Global queue manager instance
queue_manager = QueueManager()

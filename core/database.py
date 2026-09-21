import os
import json
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import aiosqlite
from core.config import settings


def get_text_hash(text: str) -> str:
    """Generate SHA256 short hash of a text string."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DATABASE_PATH
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def get_connection(self):
        """Async context manager for SQLite database connection."""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def init_db(self):
        """Create tables if they don't exist."""
        async with self.get_connection() as conn:
            await conn.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    gdrive_folder_id TEXT NOT NULL,
                    gdrive_texts_file_id TEXT DEFAULT '',
                    gdrive_footer_file_id TEXT DEFAULT '',
                    footer_text TEXT DEFAULT '',
                    photos_min INTEGER DEFAULT 2,
                    photos_max INTEGER DEFAULT 4,
                    interval_minutes INTEGER DEFAULT 180,
                    schedule_mode TEXT DEFAULT 'interval',
                    exact_times TEXT DEFAULT '10:00,15:00,20:00',
                    posts_per_day INTEGER DEFAULT 3,
                    buffer_target INTEGER DEFAULT 3,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Migration for existing databases
                CREATE TABLE IF NOT EXISTS _migrations_dummy (id INT);
            """)
            try:
                await conn.execute("ALTER TABLE channels ADD COLUMN posts_per_day INTEGER DEFAULT 3")
            except Exception:
                pass
            await conn.executescript("""

                CREATE TABLE IF NOT EXISTS used_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    photo_file_id TEXT NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, photo_file_id)
                );

                CREATE TABLE IF NOT EXISTS used_texts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, text_hash)
                );

                CREATE TABLE IF NOT EXISTS scheduled_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    scheduled_time TIMESTAMP NOT NULL,
                    caption TEXT NOT NULL,
                    photo_ids TEXT NOT NULL, -- JSON list of Google Drive file IDs
                    telegram_message_id TEXT,
                    status TEXT DEFAULT 'pending_local', -- 'pending_native', 'pending_local', 'published', 'failed'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    level TEXT DEFAULT 'INFO',
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.commit()

    # --- Channels CRUD ---
    async def get_all_channels(self) -> List[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT * FROM channels ORDER BY id ASC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_active_channels(self) -> List[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT * FROM channels WHERE is_active = 1 ORDER BY id ASC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_channel_by_id(self, channel_db_id: int) -> Optional[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT * FROM channels WHERE id = ?", (channel_db_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_channel_by_telegram_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT * FROM channels WHERE channel_id = ?", (str(channel_id),))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def create_channel(self, data: Dict[str, Any]) -> int:
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO channels (
                    channel_id, title, gdrive_folder_id, gdrive_texts_file_id,
                    gdrive_footer_file_id, footer_text, photos_min, photos_max,
                    interval_minutes, schedule_mode, exact_times, posts_per_day, buffer_target, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(data["channel_id"]),
                data.get("title", "Канал"),
                data.get("gdrive_folder_id", ""),
                data.get("gdrive_texts_file_id", ""),
                data.get("gdrive_footer_file_id", ""),
                data.get("footer_text", ""),
                data.get("photos_min", 2),
                data.get("photos_max", 4),
                data.get("interval_minutes", 180),
                data.get("schedule_mode", "interval"),
                data.get("exact_times", "10:00,15:00,20:00"),
                data.get("posts_per_day", 3),
                data.get("buffer_target", 3),
                1 if data.get("is_active", True) else 0
            ))
            await conn.commit()
            return cursor.lastrowid

    async def update_channel(self, channel_db_id: int, data: Dict[str, Any]) -> bool:
        fields = []
        values = []
        for key in [
            "channel_id", "title", "gdrive_folder_id", "gdrive_texts_file_id",
            "gdrive_footer_file_id", "footer_text", "photos_min", "photos_max",
            "interval_minutes", "schedule_mode", "exact_times", "posts_per_day", "buffer_target", "is_active"
        ]:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(channel_db_id)

        query = f"UPDATE channels SET {', '.join(fields)} WHERE id = ?"
        async with self.get_connection() as conn:
            await conn.execute(query, tuple(values))
            await conn.commit()
            return True

    async def delete_channel(self, channel_db_id: int) -> bool:
        async with self.get_connection() as conn:
            await conn.execute("DELETE FROM channels WHERE id = ?", (channel_db_id,))
            await conn.commit()
            return True

    # --- Tracking Used Media & Texts ---
    async def get_used_photo_ids(self, channel_id: str) -> set[str]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT photo_file_id FROM used_photos WHERE channel_id = ?",
                (str(channel_id),)
            )
            rows = await cursor.fetchall()
            return {row["photo_file_id"] for row in rows}

    async def mark_photos_as_used(self, channel_id: str, photo_ids: List[str]):
        async with self.get_connection() as conn:
            for pid in photo_ids:
                await conn.execute(
                    "INSERT OR IGNORE INTO used_photos (channel_id, photo_file_id) VALUES (?, ?)",
                    (str(channel_id), pid)
                )
            await conn.commit()

    async def reset_used_photos(self, channel_id: str):
        async with self.get_connection() as conn:
            await conn.execute("DELETE FROM used_photos WHERE channel_id = ?", (str(channel_id),))
            await conn.commit()

    async def get_used_text_hashes(self, channel_id: str) -> set[str]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT text_hash FROM used_texts WHERE channel_id = ?",
                (str(channel_id),)
            )
            rows = await cursor.fetchall()
            return {row["text_hash"] for row in rows}

    async def mark_text_as_used(self, channel_id: str, text: str):
        thash = get_text_hash(text)
        async with self.get_connection() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO used_texts (channel_id, text_hash) VALUES (?, ?)",
                (str(channel_id), thash)
            )
            await conn.commit()

    async def reset_used_texts(self, channel_id: str):
        async with self.get_connection() as conn:
            await conn.execute("DELETE FROM used_texts WHERE channel_id = ?", (str(channel_id),))
            await conn.commit()

    # --- Scheduled Queue (3 posts buffer) ---
    async def get_channel_queue(self, channel_id: str) -> List[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM scheduled_queue 
                WHERE channel_id = ? AND status IN ('pending_native', 'pending_local')
                ORDER BY scheduled_time ASC
                """,
                (str(channel_id),)
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["photo_ids"] = json.loads(item["photo_ids"]) if item["photo_ids"] else []
                result.append(item)
            return result

    async def add_to_queue(
        self,
        channel_id: str,
        scheduled_time: datetime,
        caption: str,
        photo_ids: List[str],
        telegram_message_id: Optional[str] = None,
        status: str = "pending_local"
    ) -> int:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO scheduled_queue (
                    channel_id, scheduled_time, caption, photo_ids, telegram_message_id, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(channel_id),
                    scheduled_time.isoformat(),
                    caption,
                    json.dumps(photo_ids),
                    str(telegram_message_id) if telegram_message_id else None,
                    status
                )
            )
            await conn.commit()
            return cursor.lastrowid

    async def mark_queue_published(self, queue_id: int):
        now_str = datetime.now().isoformat()
        async with self.get_connection() as conn:
            await conn.execute(
                """
                UPDATE scheduled_queue 
                SET status = 'published', published_at = ? 
                WHERE id = ?
                """,
                (now_str, queue_id)
            )
            await conn.commit()

    async def get_last_published_time(self, channel_id: str) -> Optional[datetime]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT published_at FROM scheduled_queue 
                WHERE channel_id = ? AND status = 'published' AND published_at IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (str(channel_id),)
            )
            row = await cursor.fetchone()
            if row and row["published_at"]:
                try:
                    return datetime.fromisoformat(row["published_at"])
                except Exception:
                    return None
            return None

    async def remove_from_queue(self, queue_id: int):
        async with self.get_connection() as conn:
            await conn.execute("DELETE FROM scheduled_queue WHERE id = ?", (queue_id,))
            await conn.commit()

    # --- Activity Logs ---
    async def add_log(self, message: str, level: str = "INFO", channel_id: Optional[str] = None):
        async with self.get_connection() as conn:
            await conn.execute(
                "INSERT INTO activity_logs (channel_id, level, message) VALUES (?, ?, ?)",
                (str(channel_id) if channel_id else None, level, message)
            )
            await conn.commit()

    async def get_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Global database instance
db = Database()

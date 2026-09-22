import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot
    BOT_TOKEN: str = Field(default="", description="Telegram Bot API token from @BotFather")
    ADMIN_IDS: str = Field(default="", description="Comma-separated Telegram user IDs of admins")
    TELEGRAM_PROXY_URL: Optional[str] = Field(
        default=None,
        description="HTTP or SOCKS5 proxy URL for Telegram Bot API (e.g. http://127.0.0.1:2080)"
    )

    # Google Drive Service Account
    GOOGLE_SERVICE_ACCOUNT_FILE: str = Field(
        default="credentials/google-service-account.json",
        description="Path to Google Service Account JSON key"
    )

    # Web / Mini App Server
    WEBAPP_HOST: str = Field(default="0.0.0.0", description="Host to bind FastAPI server")
    WEBAPP_PORT: int = Field(default=8080, description="Port to bind FastAPI server")
    WEBAPP_URL: str = Field(
        default="https://example.com",
        description="Public HTTPS URL of the Telegram Mini App"
    )

    # Database
    DATABASE_PATH: str = Field(default="data/autoposter.db", description="Path to SQLite database")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("WEBAPP_PORT", mode="before")
    @classmethod
    def parse_webapp_port(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return 8080
        return int(v)

    @property
    def admin_id_list(self) -> List[int]:
        """Parse comma-separated admin IDs into a list of integers."""
        if not self.ADMIN_IDS:
            return []
        ids = []
        for part in self.ADMIN_IDS.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    def is_admin(self, user_id: int) -> bool:
        """Check if user_id is in admin list."""
        admins = self.admin_id_list
        # If no admins configured, allow for initial setup warning
        return user_id in admins if admins else True


# Global settings singleton
settings = Settings()

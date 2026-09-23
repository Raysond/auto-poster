import io
import os
import ssl
import time
import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from core.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveService:
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path or settings.GOOGLE_SERVICE_ACCOUNT_FILE
        self._local = threading.local()
        self._creds = None

    def _get_credentials(self):
        if self._creds is None:
            if not os.path.exists(self.credentials_path):
                raise FileNotFoundError(
                    f"Файл ключа сервисного аккаунта не найден: {self.credentials_path}. "
                    "Создайте сервисный аккаунт в Google Cloud Console и положите .json ключ."
                )
            self._creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
        return self._creds

    def get_service(self, force_new: bool = False):
        """Build and cache the Google Drive API service client for the current thread."""
        if not force_new and getattr(self._local, "service", None) is not None:
            return self._local.service

        creds = self._get_credentials()
        self._local.service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._local.service

    def reset_service(self):
        """Discard cached client for the current thread on connection or SSL errors."""
        self._local.service = None

    def _execute_with_retry(self, action_fn, max_retries: int = 3, initial_delay: float = 1.0):
        """Execute a synchronous Google Drive API action with retries on transient SSL/network issues."""
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                return action_fn()
            except (ssl.SSLError, ConnectionError, OSError, TimeoutError) as e:
                last_err = e
                self.reset_service()
                logger.warning(
                    f"Временный сбой сети/SSL Google Drive (попытка {attempt}/{max_retries}): {e}"
                )
                if attempt < max_retries:
                    time.sleep(initial_delay * (2 ** (attempt - 1)))
            except Exception as e:
                # Catch wrapped socket/SSL errors
                err_str = str(e).lower()
                if "decryption failed" in err_str or "bad record mac" in err_str or "ssl" in err_str:
                    last_err = e
                    self.reset_service()
                    logger.warning(
                        f"Временный сбой SSL/MAC Google Drive (попытка {attempt}/{max_retries}): {e}"
                    )
                    if attempt < max_retries:
                        time.sleep(initial_delay * (2 ** (attempt - 1)))
                else:
                    raise
        raise last_err

    async def check_connection(self) -> Tuple[bool, str]:
        """Verify that Google Drive API credentials are valid."""
        def _check():
            try:
                service = self.get_service()
                # Try a minimal request
                about = service.about().get(fields="user").execute(num_retries=2)
                user_email = about.get("user", {}).get("emailAddress", "OK")
                return True, f"Успешное подключение: {user_email}"
            except Exception as e:
                return False, f"Ошибка авторизации Google Drive: {str(e)}"

        return await asyncio.to_thread(_check)

    async def list_images_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all image files inside a Google Drive folder."""
        if not folder_id:
            return []

        def _list():
            def _do():
                service = self.get_service()
                query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
                files = []
                page_token = None

                while True:
                    response = service.files().list(
                        q=query,
                        spaces="drive",
                        fields="nextPageToken, files(id, name, mimeType, size, thumbnailLink)",
                        pageToken=page_token,
                        pageSize=100
                    ).execute(num_retries=2)

                    files.extend(response.get("files", []))
                    page_token = response.get("nextPageToken")
                    if not page_token:
                        break

                return files

            return self._execute_with_retry(_do)

        return await asyncio.to_thread(_list)

    async def download_file_bytes(self, file_id: str) -> bytes:
        """Download a file's binary content into memory."""
        def _download():
            def _do():
                service = self.get_service()
                request = service.files().get_media(fileId=file_id)
                buffer = io.BytesIO()
                downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)

                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=2)

                buffer.seek(0)
                return buffer.getvalue()

            return self._execute_with_retry(_do)

        return await asyncio.to_thread(_download)

    async def read_text_file(self, file_id: str) -> str:
        """Download and decode a UTF-8 text file from Google Drive."""
        if not file_id:
            return ""
        data = await self.download_file_bytes(file_id)
        return data.decode("utf-8", errors="replace")

    async def get_texts_list(self, file_id: str) -> List[str]:
        """
        Read texts.txt file from Google Drive:
        Format: 1 line = 1 text option.
        Internal newlines inside a single text are encoded as literal '\\n'.
        """
        raw_content = await self.read_text_file(file_id)
        lines = []
        for line in raw_content.splitlines():
            line = line.strip()
            # Ignore empty lines and comment lines starting with #
            if not line or line.startswith("#"):
                continue
            # Replace literal \n with real newline
            parsed_text = line.replace(r"\n", "\n")
            lines.append(parsed_text)
        return lines

    async def get_footer(self, channel: Dict[str, Any]) -> str:
        """
        Get the footer/CTA for a channel.
        First checks channel['footer_text'] from DB.
        If empty, checks channel['gdrive_footer_file_id'] from Google Drive.
        """
        if channel.get("footer_text"):
            return channel["footer_text"].strip()

        footer_file_id = channel.get("gdrive_footer_file_id")
        if footer_file_id:
            try:
                content = await self.read_text_file(footer_file_id)
                return content.strip()
            except Exception as e:
                logger.warning(f"Не удалось прочитать файл футера Google Drive ({footer_file_id}): {e}")
                return ""

        return ""


# Global drive service instance
gdrive_service = GoogleDriveService()

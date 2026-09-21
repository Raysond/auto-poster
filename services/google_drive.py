import io
import os
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from core.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveService:
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path or settings.GOOGLE_SERVICE_ACCOUNT_FILE
        self._service = None

    def get_service(self):
        """Build and cache the Google Drive API service client."""
        if self._service is not None:
            return self._service

        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"Файл ключа сервисного аккаунта не найден: {self.credentials_path}. "
                "Создайте сервисный аккаунт в Google Cloud Console и положите .json ключ."
            )

        creds = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    async def check_connection(self) -> Tuple[bool, str]:
        """Verify that Google Drive API credentials are valid."""
        def _check():
            try:
                service = self.get_service()
                # Try a minimal request
                about = service.about().get(fields="user").execute()
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
                ).execute()

                files.extend(response.get("files", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            return files

        return await asyncio.to_thread(_list)

    async def download_file_bytes(self, file_id: str) -> bytes:
        """Download a file's binary content into memory."""
        def _download():
            service = self.get_service()
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            buffer.seek(0)
            return buffer.getvalue()

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
            content = await self.read_text_file(footer_file_id)
            return content.strip()

        return ""


# Global drive service instance
gdrive_service = GoogleDriveService()

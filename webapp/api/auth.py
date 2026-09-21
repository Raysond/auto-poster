import hmac
import hashlib
import json
from urllib.parse import parse_qs, unquote
from typing import Optional, Dict, Any
from fastapi import HTTPException, Header, Query
from core.config import settings


def validate_telegram_init_data(init_data_raw: str) -> Dict[str, Any]:
    """
    Validates the initData string sent by Telegram Mini App using HMAC-SHA256.
    Returns parsed user data if valid, raises HTTPException(401) otherwise.
    """
    if not init_data_raw:
        raise HTTPException(status_code=401, detail="Отсутствуют данные авторизации Telegram (initData).")

    # If BOT_TOKEN is empty in dev, allow dummy fallback
    if not settings.BOT_TOKEN or settings.BOT_TOKEN.startswith("123456789"):
        return {"id": 1, "first_name": "Dev Admin", "is_admin": True}

    parsed = parse_qs(init_data_raw)
    hash_value = parsed.get("hash", [None])[0]
    if not hash_value:
        raise HTTPException(status_code=401, detail="В initData отсутствует хэш.")

    # Data check string: alphabetically sorted key=value pairs, excluding 'hash'
    pairs = []
    for key, values in sorted(parsed.items()):
        if key != "hash":
            pairs.append(f"{key}={values[0]}")
    data_check_string = "\n".join(pairs)

    # Secret key is HMAC-SHA256 of bot token with key "WebAppData"
    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, hash_value):
        raise HTTPException(status_code=401, detail="Подпись Telegram initData недействительна.")

    user_json = parsed.get("user", [None])[0]
    user_data = json.loads(user_json) if user_json else {}
    user_id = user_data.get("id")

    if not user_id or not settings.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Доступ запрещен: пользователь не является администратором.")

    return user_data

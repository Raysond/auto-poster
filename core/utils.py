import re
from typing import Optional


def normalize_channel_id(val: Optional[str]) -> str:
    """
    Normalizes any channel input into a standard Telegram chat identifier:
    - https://t.me/svetasollars -> @svetasollars
    - http://t.me/svetasollars/ -> @svetasollars
    - t.me/svetasollars/123 -> @svetasollars
    - https://telegram.me/svetasollars -> @svetasollars
    - https://t.me/c/1234567890/10 -> -1001234567890
    - @svetasollars -> @svetasollars
    - svetasollars -> @svetasollars
    - -1001234567890 -> -1001234567890
    """
    if not val:
        return ""

    cleaned = str(val).strip()

    # 1. Check for Telegram URLs: t.me/ or telegram.me/
    # Private chat link format: t.me/c/1234567890/post_id -> channel ID -1001234567890
    c_match = re.search(r"(?:t\.me|telegram\.me)/c/(\d+)", cleaned, re.IGNORECASE)
    if c_match:
        return f"-100{c_match.group(1)}"

    # Public channel URL format: t.me/username or t.me/username/123
    u_match = re.search(r"(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)", cleaned, re.IGNORECASE)
    if u_match:
        username = u_match.group(1)
        if username.lower() not in ("joinchat", "c", "addstickers", "addtheme"):
            return f"@{username}"

    # 2. Check for numeric ID: e.g. -1001234567890, -12345, 12345
    if (cleaned.startswith("-") and cleaned[1:].isdigit()) or cleaned.isdigit():
        return cleaned

    # 3. Check for @username format
    if cleaned.startswith("@"):
        clean_user = cleaned.lstrip("@").split("/")[0].split("?")[0].strip()
        return f"@{clean_user}" if clean_user else cleaned

    # 4. Plain username without @ (e.g. svetasollars)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_]{3,}$", cleaned):
        return f"@{cleaned}"

    return cleaned

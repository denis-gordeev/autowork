from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from .config import Config


class TelegramError(RuntimeError):
    pass


def _bot_request(config: Config, method: str, payload: dict) -> dict | list:
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise TelegramError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"Telegram API error {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"Telegram network error: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramError(f"Telegram API returned error: {payload}")
    return payload["result"]


def create_topic(config: Config, project_name: str) -> Optional[int]:
    result = _bot_request(
        config,
        "createForumTopic",
        {
            "chat_id": config.telegram_chat_id,
            "name": project_name[:128],
        },
    )
    if isinstance(result, dict):
        return result.get("message_thread_id")
    return None


def send_message(config: Config, text: str, message_thread_id: Optional[int] = None) -> None:
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    _bot_request(config, "sendMessage", payload)


def get_updates(config: Config, offset: Optional[int] = None, timeout: int = 0) -> list[dict]:
    payload: dict[str, object] = {"allowed_updates": ["message"], "timeout": max(0, timeout)}
    if offset is not None:
        payload["offset"] = offset
    result = _bot_request(config, "getUpdates", payload)
    if isinstance(result, list):
        return result
    raise TelegramError(f"Unexpected getUpdates payload: {type(result)!r}")

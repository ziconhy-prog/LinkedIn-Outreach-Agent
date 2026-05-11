"""Small Telegram Bot API helper for operator-only setup checks.

This module does not send LinkedIn messages. It only verifies Telegram bot
configuration and can send a test message to the configured operator chat.
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from typing import Any

from outreach.config import TELEGRAM_BOT_TOKEN, TELEGRAM_OPERATOR_USER_ID


class TelegramConfigError(ValueError):
    """Raised when Telegram environment variables are missing or invalid."""


def require_config() -> tuple[str, str]:
    """Return configured bot token and operator user ID, or raise."""
    if not TELEGRAM_BOT_TOKEN:
        raise TelegramConfigError("TELEGRAM_BOT_TOKEN is not set in .env")
    if not TELEGRAM_OPERATOR_USER_ID:
        raise TelegramConfigError("TELEGRAM_OPERATOR_USER_ID is not set in .env")
    return TELEGRAM_BOT_TOKEN, TELEGRAM_OPERATOR_USER_ID


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _ssl_context() -> ssl.SSLContext:
    """Return a certificate context that works reliably in local venvs."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _post(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token, _ = require_config()
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        _api_url(token, method),
        data=encoded,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=_ssl_context(),
        ) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
            description = data.get("description") or body
        except json.JSONDecodeError:
            description = body or str(exc)
        raise RuntimeError(description) from exc
    data = json.loads(body)
    if not data.get("ok"):
        description = data.get("description") or "Telegram API request failed"
        raise RuntimeError(description)
    return data


def _get(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token, _ = require_config()
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    url = _api_url(token, method) + query
    try:
        with urllib.request.urlopen(url, timeout=35, context=_ssl_context()) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} failed: {body}") from exc
    data = json.loads(body)
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"{method} failed")
    return data


def get_updates(offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
    """Long-poll for new Telegram updates. Returns a list of update objects."""
    params: dict[str, Any] = {
        "timeout": timeout,
        "allowed_updates": '["message","callback_query"]',
    }
    if offset is not None:
        params["offset"] = offset
    result = _get("getUpdates", params)
    return result["result"]


def send_message(
    chat_id: int | str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a message to any chat_id (must be the operator for safety)."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    return _post("sendMessage", payload)


def get_me() -> dict[str, Any]:
    """Return Telegram bot identity."""
    token, _ = require_config()
    with urllib.request.urlopen(
        _api_url(token, "getMe"),
        timeout=20,
        context=_ssl_context(),
    ) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if not data.get("ok"):
        description = data.get("description") or "Telegram getMe failed"
        raise RuntimeError(description)
    return data["result"]


def send_operator_message(text: str) -> dict[str, Any]:
    """Send a plain text message to the configured operator chat."""
    _, operator_id = require_config()
    return send_message(operator_id, text)

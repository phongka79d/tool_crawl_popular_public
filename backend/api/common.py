"""Shared formatting and safe error messages for the desktop bridge."""
from __future__ import annotations

import logging

from backend.core import applog
from backend.core.errors import ServiceError

logger = logging.getLogger("app.api")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    applog.protect(secrets)
    return applog.redact(text)


def error_message(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    applog.protect(secrets)
    if isinstance(exc, ServiceError):
        message = redact(str(exc), secrets)
        logger.warning("%s", message)
        return message
    logger.error("Lỗi không mong đợi: %s", type(exc).__name__, exc_info=exc)
    return ("Không thể hoàn tất thao tác. Kiểm tra kết nối, quyền truy cập và cấu hình rồi thử lại. "
            "Chi tiết trong Nhật ký.")


def fail(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}

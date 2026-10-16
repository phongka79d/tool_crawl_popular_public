"""Bounded request retry, adapted from videoanalyzer (MIT)."""
from __future__ import annotations
import time
from backend.core.errors import ServiceError


def with_retry(fn, *, service='llm', retries=1, sleep=time.sleep):
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            if status in (401, 403):
                raise ServiceError(service, 'API key không hợp lệ hoặc không có quyền truy cập.') from exc
            if status == 402:
                raise ServiceError(service, 'Tài khoản API không còn hạn mức.') from exc
            if attempt == retries:
                raise
            sleep(1)

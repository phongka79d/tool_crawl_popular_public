"""Vietnamese errors for Facebook collection and browser sessions."""
from __future__ import annotations


class ServiceError(Exception):
    """Base class for failures caused by an external service."""

    def __init__(self, service: str, message: str) -> None:
        super().__init__(service, message)
        self.service = service
        self.message = message

    def __str__(self) -> str:
        return self.message


class LoginRequired(ServiceError):
    """Facebook: checkpoint, login page, or missing c_user/xs cookies."""


class BrowserUnavailable(ServiceError):
    """Facebook: the tool's browser profile is already open in another window or process."""

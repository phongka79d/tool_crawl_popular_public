"""Single optional LLM credential; masking adapted from clip-forge (MIT)."""
from __future__ import annotations

SERVICE_NAME = 'VideoCongThucPublic'
KEY_NAMES = ('llm',)


def _keyring():
    import keyring
    return keyring


def _check_name(name):
    if name not in KEY_NAMES:
        raise ValueError('Tên key không hợp lệ.')


def storage_secure():
    try:
        backend = _keyring().get_keyring()
        # Only the Windows credential vault is supported; chained/unknown stores fail closed.
        return type(backend).__module__ == 'keyring.backends.Windows' and type(backend).__name__ == 'WinVaultKeyring'
    except Exception:
        return False


def get_key(name='llm'):
    _check_name(name)
    try:
        value = _keyring().get_password(SERVICE_NAME, name) or None
        if value:
            from backend.core.applog import protect_key
            protect_key(value)
        return value
    except Exception:
        return None


def set_key(name, value):
    _check_name(name)
    cleaned = value.strip()
    if not cleaned:
        raise ValueError('API key đang trống.')
    from backend.core.applog import protect_key
    protect_key(cleaned)
    if not storage_secure():
        raise RuntimeError('Không thể lưu API key: hãy bật Windows Credential Manager. Không lưu key dạng chữ thường.')
    _keyring().set_password(SERVICE_NAME, name, cleaned)


def delete_key(name='llm'):
    _check_name(name)
    kr = _keyring()
    if kr.get_password(SERVICE_NAME, name) is not None:
        kr.delete_password(SERVICE_NAME, name)


def mask(key):
    cleaned = (key or '').strip()
    return '' if not cleaned else '••••' + (cleaned[-4:] if len(cleaned) > 8 else '')

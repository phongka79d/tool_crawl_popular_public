"""Optional credential-backed transcript enhancement settings."""
from urllib.parse import urlsplit
from backend.core import config, keys
from backend.core.applog import protect_key, redact
from backend.services import llm_client
from backend.api.common import fail

PROVIDERS = [
    {'label': 'OpenAI', 'url': 'https://api.openai.com/v1'},
    {'label': 'Anthropic (Claude)', 'url': 'https://api.anthropic.com/v1/'},
    {'label': 'OpenRouter', 'url': 'https://openrouter.ai/api/v1'},
    {'label': 'Khác (OpenAI-compatible, tự nhập)', 'url': ''},
]
RECOMMENDED_MODELS = {
    'https://api.openai.com/v1': ['gpt-4.1-mini', 'gpt-4o-mini'],
    'https://api.anthropic.com/v1': ['claude-haiku-4-5', 'claude-haiku'],
    'https://openrouter.ai/api/v1': ['anthropic/claude-haiku-4.5', 'openai/gpt-4.1-mini'],
}


def provider_name(url):
    return next((p['label'] for p in PROVIDERS[:-1] if p['url'].rstrip('/') == url.rstrip('/')), PROVIDERS[-1]['label'])


def get_llm():
    saved = config.load_settings()['llm']
    key = keys.get_key()
    return dict(ok=True, providers=PROVIDERS, base_url=redact(saved['base_url']), model=redact(saved['model']),
                provider=provider_name(saved['base_url']) if saved['base_url'] else 'OpenAI',
                saved_mask=keys.mask(key), enabled=bool(key and saved['base_url'] and saved['model']),
                storage_secure=keys.storage_secure(), recommended_models=RECOMMENDED_MODELS)


def _candidate(key, base_url):
    candidate = key.strip() or keys.get_key() or ''
    protect_key(candidate)
    if not candidate:
        raise ValueError('Vui lòng nhập API key.')
    parts = urlsplit(base_url.strip())
    # http chỉ cho máy chủ chạy trên chính máy này (LM Studio, Ollama…); key không đi qua mạng ngoài.
    local = parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')
    if not (parts.scheme == 'https' or local) or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Endpoint phải là địa chỉ https:// (hoặc http://localhost) hợp lệ, không chứa thông tin đăng nhập, query hay fragment.')
    return candidate


def connect_llm(key, base_url):
    try:
        candidate = _candidate(key, base_url)
        models = llm_client.list_models(base_url.strip(), candidate)
        if not models:
            return fail('Nhà cung cấp không trả về model nào.')
        preferences = RECOMMENDED_MODELS.get(base_url.strip().rstrip('/'), [])
        recommended = next((m['id'] for prefix in preferences for m in models if m['id'].startswith(prefix)), None)
        safe = [{'id': redact(m['id']), 'label': redact(m['id'])} for m in models]
        return dict(ok=True, models=safe, default_id=redact(recommended or models[0]['id']), recommended_id=redact(recommended or ''))
    except Exception as exc:
        return fail(redact(str(exc)))


def save_llm(key, base_url, model):
    from backend.api import scan
    if scan.is_running():
        return fail('Hãy chờ quét hoàn tất trước khi thay đổi key.')
    if not keys.storage_secure():
        return fail('Không thể lưu API key: hãy bật Windows Credential Manager. Không lưu key dạng chữ thường.')
    try:
        candidate = _candidate(key, base_url)
        if not isinstance(model, str) or not model.strip():
            return fail('Vui lòng chọn model.')
        llm_client.check_key(base_url.strip(), candidate, model.strip())
        settings = config.load_settings()
        keys.set_key('llm', candidate)
        settings['llm'] = {'base_url': base_url.strip(), 'model': model.strip()}
        config.save_settings(settings)
        return dict(ok=True, message='Đã kiểm tra và lưu key cải thiện lời thoại.')
    except Exception as exc:
        return fail(redact(str(exc)))


def remove_llm():
    from backend.api import scan
    if scan.is_running():
        return fail('Hãy chờ quét hoàn tất trước khi xoá key.')
    keys.delete_key()
    settings = config.load_settings()
    settings['llm'] = {'base_url': '', 'model': ''}
    config.save_settings(settings)
    return dict(ok=True, message='Đã xoá key. App vẫn chép lời bình thường trên máy.')

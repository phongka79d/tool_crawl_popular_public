from copy import deepcopy
from unittest.mock import Mock
import pytest
from backend.api import llm, scan, app_state, channels
from backend.core import config, keys


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(config, 'SETTINGS_FILE', tmp_path / 'settings.json')
    config.save_settings(deepcopy(config.DEFAULT_SETTINGS))
    monkeypatch.setattr(keys, 'get_key', lambda: 'saved-test-credential')
    monkeypatch.setattr(keys, 'storage_secure', lambda: True)
    monkeypatch.setattr(scan, 'is_running', lambda: False)


def test_exact_providers_and_key_alone_off():
    result = llm.get_llm()
    assert [p['label'] for p in result['providers']] == ['OpenAI', 'Anthropic (Claude)', 'OpenRouter', 'Khác (OpenAI-compatible, tự nhập)']
    assert not result['enabled']
    assert 'saved-test-credential' not in str(result)


def test_connect_recommends_without_saving(monkeypatch):
    fetch = Mock(return_value=[{'id': 'aaa'}, {'id': 'gpt-4.1-mini'}])
    monkeypatch.setattr(llm.llm_client, 'list_models', fetch)
    before = config.SETTINGS_FILE.read_bytes()
    result = llm.connect_llm('', 'https://api.openai.com/v1')
    assert result['default_id'] == result['recommended_id'] == 'gpt-4.1-mini'
    fetch.assert_called_once_with('https://api.openai.com/v1', 'saved-test-credential')
    assert config.SETTINGS_FILE.read_bytes() == before


def test_save_checks_then_stores_and_remove_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.llm_client, 'check_key', lambda *args: calls.append(('check', args)))
    monkeypatch.setattr(keys, 'set_key', lambda *args: calls.append(('save', args)))
    monkeypatch.setattr(keys, 'delete_key', lambda: calls.append(('delete',)))
    assert llm.save_llm('candidate-credential', 'https://example.com/v1', 'model')['ok']
    assert [call[0] for call in calls] == ['check', 'save']
    assert config.load_settings()['llm'] == {'base_url': 'https://example.com/v1', 'model': 'model'}
    assert 'candidate-credential' not in config.SETTINGS_FILE.read_text()
    assert llm.remove_llm()['ok']
    assert config.load_settings()['llm'] == {'base_url': '', 'model': ''}
    assert calls[-1] == ('delete',)


def test_insecure_save_rejected_before_check(monkeypatch):
    monkeypatch.setattr(keys, 'storage_secure', lambda: False)
    monkeypatch.setattr(llm.llm_client, 'check_key', lambda *args: pytest.fail('should refuse'))
    assert 'Credential Manager' in llm.save_llm('candidate', 'https://example.com', 'model')['error']


def test_candidate_error_and_metadata_redacted(monkeypatch):
    key = 'candidate-private-credential'
    monkeypatch.setattr(llm.llm_client, 'list_models', lambda *args: [{'id': key}])
    assert key not in str(llm.connect_llm(key, 'https://example.com'))
    def fail(*args):
        raise RuntimeError(key)
    monkeypatch.setattr(llm.llm_client, 'check_key', fail)
    assert key not in str(llm.save_llm(key, 'https://example.com', 'model'))


def test_reset_deletes_key(monkeypatch):
    deleted = Mock()
    monkeypatch.setattr(keys, 'delete_key', deleted)
    monkeypatch.setattr(channels, 'is_logging_in', lambda: False)
    assert app_state.reset_configuration()['ok']
    deleted.assert_called_once_with()


@pytest.mark.parametrize('url', ['http://example.com/v1', 'https://user:pass@example.com', 'https://example.com?key=secret', 'file:///path'])
def test_invalid_endpoint_refuses_network(monkeypatch, url):
    monkeypatch.setattr(llm.llm_client, 'list_models', lambda *args: pytest.fail('network'))
    assert not llm.connect_llm('candidate', url)['ok']


@pytest.mark.parametrize('url', ['http://localhost:1234/v1', 'http://127.0.0.1:11434/v1'])
def test_local_http_endpoint_is_allowed(monkeypatch, url):
    monkeypatch.setattr(llm.llm_client, 'list_models', lambda *args: [{'id': 'local-model'}])
    assert llm.connect_llm('candidate', url)['ok']

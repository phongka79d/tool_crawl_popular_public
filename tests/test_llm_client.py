import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from backend.services import llm_client as llm
from backend.core.models import Video


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(llm, 'OpenAI', MagicMock(return_value=client))
    return client


def response(data):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))])


def test_anthropic_headers_and_models(client):
    client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id='z'), SimpleNamespace(id='a')])
    assert llm.list_models('https://api.anthropic.com/v1/', 'candidate-key') == [{'id': 'a'}, {'id': 'z'}]
    kwargs = llm.OpenAI.call_args.kwargs
    assert kwargs['default_headers']['anthropic-version'] == '2023-06-01'
    assert kwargs['default_headers']['x-api-key'] == 'candidate-key'
    assert kwargs['max_retries'] == 0
    client.models.list.assert_called_once_with(extra_query={'limit': 1000})


def test_check_real_completion_and_max_tokens_fallback(client):
    error = RuntimeError('max_tokens unsupported')
    error.status_code = 400
    client.chat.completions.create.side_effect = [error, response([])]
    llm.check_key('https://api.openai.com/v1', 'candidate-key', 'model')
    assert client.chat.completions.create.call_args.kwargs['max_completion_tokens'] == 1


def test_robust_array_extraction():
    assert llm.parse_json_array('Text ```json\n[{"id":"1"}]\n``` end') == [{'id': '1'}]
    with pytest.raises(ValueError):
        llm.parse_json_array('{"wrong":true}')


def test_batch_retries_invalid_json_once(client, monkeypatch):
    monkeypatch.setattr(llm, 'with_retry', lambda fn, **kwargs: retry_twice(fn))
    client.chat.completions.create.side_effect = [response([]), response([{'id': '1', 'co_loi_noi': True, 'thoai': 'Đúng.'}])]
    video = Video('1', '', '', transcript='dung')
    assert llm.enhance_batch('https://example.com/v1', 'candidate-key', 'model', [video])['1']['thoai'] == 'Đúng.'
    assert client.chat.completions.create.call_count == 2


def retry_twice(fn):
    try:
        return fn()
    except ValueError:
        return fn()


@pytest.mark.parametrize('items', [
    [{'id': '2', 'co_loi_noi': True, 'thoai': 'text'}],
    [{'id': '1', 'co_loi_noi': 'false', 'thoai': ''}],
    [{'id': '1', 'co_loi_noi': True, 'thoai': ''}],
])
def test_batch_rejects_bad_schema(client, monkeypatch, items):
    monkeypatch.setattr(llm, 'with_retry', lambda fn, **kwargs: fn())
    client.chat.completions.create.return_value = response(items)
    with pytest.raises(ValueError):
        llm.enhance_batch('https://example.com/v1', 'candidate-key', 'model', [Video('1', '', '')])

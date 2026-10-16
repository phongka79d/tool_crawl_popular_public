import sys
import os
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.collectors import transcript
from backend.core import config, db
from backend.core.models import Video


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'cache.db')
    db.init_db()
    paths, calls = [], []
    def download(url, directory):
        target = directory / 'audio.mp4'
        target.write_bytes(b'audio')
        paths.append(target)
        return target
    monkeypatch.setattr(transcript.ytdlp, 'download_audio', download)
    class Model:
        def __init__(self, *args, **kwargs):
            calls.append(('model', args, kwargs))
        def transcribe(self, path, **kwargs):
            calls.append(('transcribe', path, kwargs))
            return iter([SimpleNamespace(text=' Đây là lời thoại tiếng Việt đủ dài để xuất ra tệp Excel. ')]), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    return paths, calls


def test_lazy_single_model_for_run_forced_vietnamese_and_cleanup(environment):
    paths, calls = environment
    worker = transcript.Transcriber()
    assert calls == []
    for identity in ('1', '2'):
        text, status = transcript.get_transcript(Video(identity, identity, 'a'), worker)
        assert status == 'ok' and len(text) >= 30
    assert len([call for call in calls if call[0] == 'model']) == 1
    assert calls[0][1] == ('small',)
    assert calls[0][2] == {'device': 'cpu', 'compute_type': 'int8',
        'cpu_threads': max(1, (os.cpu_count() or 1) // 2), 'num_workers': 1,
        'download_root': str(config.DATA_DIR / 'models')}
    assert all(call[2] == {'language': 'vi', 'vad_filter': True, 'beam_size': 1,
                          'condition_on_previous_text': False} for call in calls if call[0] == 'transcribe')
    assert all(not path.exists() and not path.parent.exists() for path in paths)


def test_cache_avoids_download_and_model(environment):
    paths, calls = environment
    db.save_transcript('1', 'cached speech', 'ok')
    video = Video('1', '1', 'a')
    assert transcript.get_transcript(video) == ('cached speech', 'ok')
    assert video.transcript == 'cached speech' and not paths and not calls


def test_no_speech_cached_and_failure_cleans_files(environment):
    paths, calls = environment
    worker = SimpleNamespace(transcribe=lambda path: 'ngắn')
    assert transcript.get_transcript(Video('1', '1', 'a'), worker) == ('ngắn', 'no_speech')
    assert db.get_transcript('1') == ('ngắn', 'no_speech')
    def fail(path):
        raise RuntimeError('decode failed')
    with pytest.raises(RuntimeError, match='decode failed'):
        transcript.get_transcript(Video('2', '2', 'a'), SimpleNamespace(transcribe=fail))
    assert all(not path.parent.exists() for path in paths)


def test_stopped_before_download(environment):
    stop = threading.Event()
    stop.set()
    assert transcript.get_transcript(Video('1', '1', 'a'), stop=stop) == ('', '')
    assert environment == ([], [])

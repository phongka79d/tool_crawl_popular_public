import threading
from types import SimpleNamespace
import pytest
from backend.core import config, db
from backend.core.models import Page, Video
from backend.core.errors import LoginRequired, ServiceError
from backend.services import pipeline

TEXT = 'Đây là một kịch bản tiếng Việt có đầy đủ lời nói để lưu và xuất thành nội dung.'
PAGE = 'https://www.facebook.com/Example'


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'data/cache.db')
    monkeypatch.setattr(config, 'OUTPUT_DIR', tmp_path / 'output')
    monkeypatch.setattr(config, 'PROFILE_DIR', tmp_path / 'profile')
    monkeypatch.setattr(config, 'load_lines', lambda _: [PAGE])
    state = SimpleNamespace(rows=[{'video_id': '1', 'url': 'https://example/1', 'views': 100000,
                                   'posted_at': 1900000000, 'format': 'video'}],
                            login=None, failure=None, calls=[], events=[], pauses=[], stop=threading.Event())
    class Scanner:
        scan_errors = []
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def check_login(self):
            if state.login:
                raise state.login
        def get_page_info(self, url):
            return Page(url, 'Example', 0)
        def scan_page(self, *args, **kwargs):
            if state.failure:
                raise state.failure
            return state.rows
        def polite_page_pause(self, **kwargs):
            state.pauses.append(True)
    monkeypatch.setattr(pipeline, 'FacebookScanner', Scanner)
    monkeypatch.setattr(pipeline.ytdlp, 'fill_missing', lambda v: state.calls.append(('metadata', v.video_id)))
    def transcribe(video, worker, stop):
        state.calls.append(('transcribe', video.video_id))
        video.transcript = TEXT
        video.transcript_status = 'ok'
        return TEXT, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    state.run = lambda: pipeline.run(pipeline.RunParams(viral_factor=1), config.DEFAULT_SETTINGS,
                                     state.stop, state.events.append)
    return state


def test_scan_transcribe_export_history_and_progress(harness):
    state = harness
    path = state.run()
    assert path.exists() and ('transcribe', '1') in state.calls
    assert db.get_taken('1')['status'] == 'taken'
    complete = [event for event in state.events if event.found is not None]
    assert len(complete) == 1 and (complete[0].found, complete[0].passed) == (1, 1)
    assert complete[0].page_url == PAGE
    assert state.events[-1].stage == 'done' and state.events[-1].done
    summary = pipeline.export_excel.read_summary(path)
    assert summary['new'] == 1


def test_taken_reused_without_transcription(harness):
    state = harness
    config.ensure_dirs()
    db.init_db()
    db.save_taken(Video('1', 'https://example/1', PAGE, page_name='Example', transcript=TEXT),
                  'taken', '2026-10-01')
    path = state.run()
    assert not any(call[0] == 'transcribe' for call in state.calls)
    summary = pipeline.export_excel.read_summary(path)
    assert summary['taken_before'] == 1 and summary['top'][0]['status'] == 'Đã lấy ngày 01/10'
    assert summary['top'][0]['transcript'] == TEXT


@pytest.mark.parametrize('status', ['duplicate_script', 'no_speech'])
def test_history_skip_is_silent(harness, status):
    config.ensure_dirs()
    db.init_db()
    db.save_taken(Video('1', '1', PAGE), status, '2026-10-01')
    path = harness.run()
    assert pipeline.export_excel.read_summary(path)['total'] == 0
    assert not any(call[0] == 'transcribe' for call in harness.calls)


def test_partial_rows_survive_service_failure(harness):
    error = ServiceError('facebook', 'mất kết nối')
    error.partial_rows = harness.rows
    harness.failure = error
    path = harness.run()
    result = pipeline.export_excel.read_summary(path)
    assert result['new'] == 1 and result['errors'] == ['LỖI: mất kết nối']


def test_login_failure_has_no_export(harness):
    harness.login = LoginRequired('facebook', 'Cần đăng nhập')
    assert harness.run() is None
    assert not harness.calls


def test_metadata_before_viral_filter(harness, monkeypatch):
    harness.rows[0]['posted_at'] = None
    harness.rows[0]['views'] = None
    def fill(video):
        video.views = 100000
        video.posted_at = 1900000000
        harness.calls.append(('metadata', video.video_id))
    monkeypatch.setattr(pipeline.ytdlp, 'fill_missing', fill)
    assert harness.run() is not None
    assert harness.calls[:2] == [('metadata', '1'), ('transcribe', '1')]


def test_no_speech_history(harness, monkeypatch):
    def transcribe(video, *args):
        video.transcript = 'ngắn'
        return 'ngắn', 'no_speech'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['new'] == 0
    assert result['notes'] == ['Bỏ qua (không có lời nói): https://example/1']
    assert db.get_taken('1')['status'] == 'no_speech'


def test_stop_before_any_data_has_no_export(harness):
    harness.stop.set()
    assert harness.run() is None


def test_cli_forwards_public_options(monkeypatch):
    captured = []
    monkeypatch.setattr(pipeline, 'run', lambda params, **kwargs: captured.append(params) or 'output.xlsx')
    assert pipeline.main(['--days', '7', '--min-views', '123', '--viral-factor', '2',
                          '--max-per-channel', '4', '--formats', 'reel']) == 0
    params = captured[0]
    assert (params.days, params.min_views, params.viral_factor, params.max_per_channel, params.formats) == (
        7, 123, 2, 4, frozenset({'reel'}))


def test_batch_script_group_and_history_dedupe(harness):
    harness.rows.append(dict(harness.rows[0], video_id='2', url='https://example/2'))
    path = harness.run()
    assert pipeline.export_excel.read_summary(path)['total'] == 1
    assert db.get_taken('1')['status'] == 'taken'
    assert db.get_taken('2')['status'] == 'duplicate_script'
    harness.rows = [dict(harness.rows[0], video_id='3', url='https://example/3')]
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['total'] == 0
    assert any('kịch bản đã lấy ngày' in note for note in result['notes'])
    assert db.get_taken('3')['status'] == 'duplicate_script'


def test_stop_after_transcription_exports_completed_work(harness, monkeypatch):
    harness.rows.append(dict(harness.rows[0], video_id='2', url='https://example/2'))
    def transcribe(video, *args):
        video.transcript = TEXT
        harness.stop.set()
        return TEXT, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    path = harness.run()
    assert pipeline.export_excel.read_summary(path)['new'] == 1
    assert db.get_taken('2') is None


def test_invalid_channel_skipped_and_between_channel_pause(harness, monkeypatch):
    other = 'https://www.facebook.com/Other'
    monkeypatch.setattr(config, 'load_lines', lambda _: ['not-a-page', PAGE, other])
    path = harness.run()
    assert path.exists() and len(harness.pauses) == 1
    assert any(event.found == 0 and event.passed == 0 for event in harness.events)


def enable_llm(harness, monkeypatch):
    from copy import deepcopy
    settings = deepcopy(config.DEFAULT_SETTINGS)
    settings['llm'] = {'base_url': 'https://example.com/v1', 'model': 'model'}
    monkeypatch.setattr(pipeline.keys, 'get_key', lambda: 'pipeline-test-credential')
    monkeypatch.setattr(pipeline.llm_client, 'check_key', lambda *args: None)
    harness.run = lambda: pipeline.run(pipeline.RunParams(viral_factor=1), settings,
                                      harness.stop, harness.events.append)


def test_without_key_makes_no_llm_calls(harness, monkeypatch):
    monkeypatch.setattr(pipeline.llm_client, 'check_key', lambda *args: pytest.fail('unexpected check'))
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', lambda *args: pytest.fail('unexpected AI'))
    assert harness.run()


def test_enhanced_excel_raw_history_and_reuse(harness, monkeypatch):
    enable_llm(harness, monkeypatch)
    cleaned = 'Lời thoại đã sửa, khác hoàn toàn bản gốc để kiểm tra lọc trùng.'
    calls = []
    def enhance(*args):
        calls.append([v.video_id for v in args[-1]])
        return {'1': {'co_loi_noi': True, 'thoai': cleaned}}
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', enhance)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['top'][0]['transcript'] == cleaned
    assert db.get_taken('1')['transcript'] == TEXT
    assert db.get_taken('1')['transcript_clean'] == cleaned
    assert any(event.stage == 'enhance' for event in harness.events)
    assert pipeline.export_excel.read_summary(harness.run())['top'][0]['transcript'] == cleaned
    assert calls == [['1']]
    harness.rows = [dict(harness.rows[0], video_id='2')]
    assert pipeline.export_excel.read_summary(harness.run())['total'] == 0
    assert db.get_taken('2')['status'] == 'duplicate_script'
    assert calls == [['1']]


def test_enhancement_failure_keeps_raw_and_note(harness, monkeypatch):
    enable_llm(harness, monkeypatch)
    def fail(*args):
        raise RuntimeError('network unavailable')
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', fail)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['top'][0]['transcript'] == TEXT
    assert result['errors'] == ['LỖI: Không cải thiện được lời thoại: network unavailable']
    assert not db.get_taken('1')['transcript_clean']


def test_key_precheck_failure_does_not_gate_scan(harness, monkeypatch):
    enable_llm(harness, monkeypatch)
    def fail(*args):
        raise RuntimeError('invalid credential')
    monkeypatch.setattr(pipeline.llm_client, 'check_key', fail)
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', lambda *args: pytest.fail('disabled'))
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['total'] == 1
    assert 'Không cải thiện được lời thoại' in result['errors'][0]


def test_llm_no_speech_drops_row(harness, monkeypatch):
    enable_llm(harness, monkeypatch)
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch',
                        lambda *args: {'1': {'co_loi_noi': False, 'thoai': ''}})
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['total'] == 0
    assert result['notes'] == ['Bỏ qua (nhạc / bài hát, không phải lời nói): https://example/1']
    assert db.get_taken('1')['status'] == 'no_speech'


@pytest.mark.parametrize('cancel,expected', [(False, [8, 1]), (True, [8])])
def test_enhancement_batches_and_cancel_between_batches(harness, monkeypatch, cancel, expected):
    enable_llm(harness, monkeypatch)
    harness.rows = [dict(harness.rows[0], video_id=str(n), url=f'https://example/{n}') for n in range(9)]
    # Isolate batching from script grouping; script dedupe has dedicated integration coverage.
    monkeypatch.setattr(pipeline.filters, 'dedupe_scripts', lambda videos, *args: (videos, [], []))
    sizes = []
    def enhance(*args):
        batch = args[-1]
        sizes.append(len(batch))
        if cancel:
            harness.stop.set()
        return {video.video_id: {'co_loi_noi': True, 'thoai': 'Đã sửa.'} for video in batch}
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', enhance)
    result = pipeline.export_excel.read_summary(harness.run())
    assert sizes == expected and result['total'] == 9
    events = [event for event in harness.events if event.stage == 'enhance']
    assert all(event.steps == 9 for event in events)


def test_llm_failure_redacts_progress_and_excel(harness, monkeypatch):
    enable_llm(harness, monkeypatch)
    def fail(*args):
        raise RuntimeError('provider echoed pipeline-test-credential')
    monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', fail)
    result = pipeline.export_excel.read_summary(harness.run())
    assert 'pipeline-test-credential' not in str(result)
    assert 'pipeline-test-credential' not in str(harness.events)
    assert '[đã che]' in result['errors'][0]


def test_export_receives_structured_scan_context(harness, monkeypatch):
    original = pipeline.export_excel.export
    captured = {}
    def export(videos, scan_lines, notes, **kwargs):
        captured.update(kwargs)
        captured['videos'] = videos
        return original(videos, scan_lines, notes, **kwargs)
    monkeypatch.setattr(pipeline.export_excel, 'export', export)
    harness.rows[0].update(reactions=50, comments=0, shares=10)
    assert harness.run().exists()
    stats = captured['channel_stats']
    assert stats == [dict(url=PAGE, name='Example', followers=0, scanned=1, recent=1,
                          median=100000, threshold=100000, selected=1, highest_views=100000)]
    context = captured['run_log']
    assert context['started_at'] <= context['finished_at']
    assert context['params']['viral_factor'] == 1 and context['params']['days'] == 14
    assert context['channel_count'] == 1 and context['llm'] is None
    video = captured['videos'][0]
    assert video.interactions == 60 and video.ratio_median == 1
    assert video.ratio_follow is None and video.engagement == 0.0006 and video.share_rate == 0.0001


def test_reused_rows_keep_current_scan_metrics(harness):
    from openpyxl import load_workbook
    config.ensure_dirs()
    db.init_db()
    db.save_taken(Video('1', 'https://example/1', PAGE, page_name='Former name', views=20,
                        transcript=TEXT, transcript_clean='Bản đã sửa'), 'taken', '2026-10-01')
    path = harness.run()
    workbook = load_workbook(path)
    try:
        sheet = workbook['Chi tiết video']
        assert sheet['B3'].value == 'Example' and sheet['H3'].value == '100 nghìn'
        assert sheet['N3'].value == 1
        assert sheet['S3'].value == 'Bản đã sửa'
        assert sheet['X3'].value == 'Lời thoại đã được AI sửa'
    finally:
        workbook.close()


@pytest.mark.parametrize('enhance', [False, True])
def test_channel_work_overlaps_next_scan_and_dedupe_is_global(harness, monkeypatch, enhance):
    other = 'https://www.facebook.com/Other'
    monkeypatch.setattr(config, 'load_lines', lambda _: [PAGE, other])
    completed = threading.Event()
    scanner_thread = threading.get_ident()
    original = pipeline.FacebookScanner
    if enhance:
        enable_llm(harness, monkeypatch)
        def improve(*args):
            assert threading.get_ident() != scanner_thread
            completed.set()
            return {v.video_id: {'co_loi_noi': True, 'thoai': TEXT} for v in args[-1]}
        monkeypatch.setattr(pipeline.llm_client, 'enhance_batch', improve)
    def transcribe(video, *args):
        assert threading.get_ident() != scanner_thread
        video.transcript = TEXT
        if not enhance:
            completed.set()
        return TEXT, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    class Scanner(original):
        def scan_page(self, url, **kwargs):
            assert threading.get_ident() == scanner_thread
            if url == other:
                assert completed.wait(5), 'Channel 1 must finish while channel 2 is scanning'
                return [dict(harness.rows[0], video_id='2', url='https://example/2', views=200000)]
            return harness.rows
    monkeypatch.setattr(pipeline, 'FacebookScanner', Scanner)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['total'] == 1
    assert db.get_taken('2')['status'] == 'taken'
    assert db.get_taken('1')['status'] == 'duplicate_script'
    events = [event for event in harness.events if event.stage == 'transcribe']
    assert events[0].page_url == PAGE and events[-1].page_url == other


def test_stop_during_next_scan_preserves_completed_transcription(harness, monkeypatch):
    other = 'https://www.facebook.com/Other'
    monkeypatch.setattr(config, 'load_lines', lambda _: [PAGE, other])
    completed = threading.Event()
    original = pipeline.FacebookScanner
    second_started = threading.Event()
    def transcribe(video, *args):
        assert second_started.wait(5)
        video.transcript = TEXT
        completed.set()
        harness.stop.set()
        return TEXT, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    class Scanner(original):
        def polite_page_pause(self, **kwargs):
            pass
        def scan_page(self, url, **kwargs):
            if url == other:
                second_started.set()
                assert completed.wait(5)
                return [dict(harness.rows[0], video_id='2')]
            return harness.rows
    monkeypatch.setattr(pipeline, 'FacebookScanner', Scanner)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['new'] == 1 and db.get_taken('2') is None
    assert any('Đã dừng' in note for note in result['errors'])


def test_only_known_old_metadata_can_be_skipped(harness, monkeypatch):
    harness.rows = [
        dict(harness.rows[0], video_id='old', posted_at=1, views=None),
        dict(harness.rows[0], video_id='low', posted_at=None, views=100),
        dict(harness.rows[0], video_id='high', views=100000),
    ]
    def fill(video):
        harness.calls.append(('metadata', video.video_id))
        video.posted_at = 1900000000
    monkeypatch.setattr(pipeline.ytdlp, 'fill_missing', fill)
    assert harness.run()
    assert ('metadata', 'old') not in harness.calls
    assert ('metadata', 'low') in harness.calls


def test_stop_keeps_history_rows_from_already_scanned_channel(harness, monkeypatch):
    config.ensure_dirs()
    db.init_db()
    db.save_taken(Video('2', 'https://example/2', PAGE, transcript=TEXT), 'taken', '2026-10-01')
    harness.rows.append(dict(harness.rows[0], video_id='2', url='https://example/2', views=90000))
    def transcribe(video, *args):
        video.transcript = 'Kịch bản mới khác hẳn nội dung lưu trước để không bị lọc trùng.'
        harness.stop.set()
        return video.transcript, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    # Both videos must qualify independently of the channel median.
    result = pipeline.export_excel.read_summary(pipeline.run(
        pipeline.RunParams(viral_factor=0.5), config.DEFAULT_SETTINGS, harness.stop))
    assert result['taken_before'] == 1 and result['new'] == 1


def test_error_in_next_channel_exports_completed_overlap_work(harness, monkeypatch):
    other = 'https://www.facebook.com/Other'
    monkeypatch.setattr(config, 'load_lines', lambda _: [PAGE, other])
    completed = threading.Event()
    original = pipeline.FacebookScanner
    def transcribe(video, *args):
        video.transcript = TEXT
        completed.set()
        return TEXT, 'ok'
    monkeypatch.setattr(pipeline.transcript, 'get_transcript', transcribe)
    class Scanner(original):
        def scan_page(self, url, **kwargs):
            if url == other:
                assert completed.wait(5)
                raise ServiceError('facebook', 'lỗi kênh kế tiếp')
            return harness.rows
    monkeypatch.setattr(pipeline, 'FacebookScanner', Scanner)
    result = pipeline.export_excel.read_summary(harness.run())
    assert result['new'] == 1 and db.get_taken('1')['status'] == 'taken'
    assert any('lỗi kênh kế tiếp' in message for message in result['errors'])

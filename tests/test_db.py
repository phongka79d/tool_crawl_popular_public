import json
import pytest
from backend.core import db
from backend.core.models import Page, Video


@pytest.fixture
def path(tmp_path):
    target = tmp_path / 'cache.db'
    db.init_db(target)
    db.init_db(target)
    return target


def test_schema(path):
    with db.conn(path) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            'pages', 'videos', 'runs', 'taken', 'sqlite_sequence'}


def test_refresh_preserves_metadata_and_transcript(path):
    video = Video('1', 'https://example/1', 'page', views=0, caption='caption', transcript='stored',
                  transcript_status='ok', transcript_language='vi')
    db.upsert_video(video, path)
    db.upsert_video(Video('1', '', '', views=None, transcript_status='failed'), path)
    stored = db.get_video('1', path)
    assert (stored.url, stored.page_url, stored.views, stored.caption) == ('https://example/1', 'page', 0, 'caption')
    assert db.get_transcript('1', path) == ('stored', 'ok')
    db.save_transcript('1', 'replacement', 'ok', path)
    assert db.get_transcript('1', path) == ('replacement', 'ok')


def test_page_and_run_logs(path):
    db.upsert_page(Page('page', 'Name', 123), path)
    db.upsert_page(Page('page'), path)
    with db.conn(path) as connection:
        row = connection.execute('SELECT * FROM pages').fetchone()
        assert row['name'] == 'Name' and row['followers'] == 123
    run = db.start_run({'formats': frozenset({'video', 'reel'})}, path)
    db.finish_run(run, {'message': 'xong'}, path)
    with db.conn(path) as connection:
        row = connection.execute('SELECT * FROM runs').fetchone()
        assert row['finished_at'] is not None
        assert json.loads(row['params_json'])['formats'] == ['reel', 'video']
    with pytest.raises(ValueError):
        db.finish_run(run + 1, {}, path)


@pytest.mark.parametrize('status', ['taken', 'duplicate_script', 'no_speech'])
def test_history_status_and_retrieval(path, status):
    video = Video('1', 'https://example/1', 'a', page_name='A', views=123, transcript='speech')
    db.save_taken(video, status, '2026-10-16', path)
    entry = db.get_taken('1', path)
    assert entry['taken_on'] == '2026-10-16' and entry['status'] == status
    assert len(db.list_taken(path)) == (1 if status == 'taken' else 0)
    assert db.get_taken('missing', path) is None


def test_existing_history_migrates_clean_column(tmp_path):
    target = tmp_path / 'old.db'
    with db.conn(target) as connection:
        connection.execute('CREATE TABLE taken (video_id TEXT PRIMARY KEY, url TEXT, page_name TEXT, views INTEGER, posted_at INTEGER, transcript TEXT, taken_on TEXT, status TEXT)')
        connection.execute("INSERT INTO taken VALUES ('1','url','page',100,NULL,'raw','2026-10-01','taken')")
    db.init_db(target)
    db.init_db(target)
    assert db.get_taken('1', target)['transcript'] == 'raw'
    assert db.get_taken('1', target)['transcript_clean'] is None
    db.save_taken(Video('1', 'url', 'page', transcript='raw', transcript_clean='Clean.'),
                  'taken', '2026-10-01', target)
    assert db.get_taken('1', target)['transcript_clean'] == 'Clean.'

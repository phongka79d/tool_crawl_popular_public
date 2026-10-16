from backend.core.models import Video
from backend.services import filters


def video(identity, views, page='a', posted=None, text=''):
    return Video(str(identity), f'https://example/{identity}', page, page_name=page,
                 views=views, posted_at=posted, transcript=text)


def test_exact_threshold_and_minimum_domination():
    rows = [video(1, 100), video(2, 100), video(3, 300)]
    selection = filters.select_channel(rows, min_views=0, viral_factor=3)
    assert selection.median == 100
    assert selection.threshold == 300
    assert selection.videos == [rows[2]]
    assert filters.select_channel(rows, min_views=301, viral_factor=3).videos == []


def test_cap_and_each_channel_baseline():
    rows = [video(n, n * 100) for n in range(1, 6)]
    assert [v.views for v in filters.select_channel(rows, min_views=0, viral_factor=1,
                                                  max_per_channel=2).videos] == [500, 400]
    assert len(filters.apply_filter(rows + [video(6, 1, 'b')], min_views=0,
                                    viral_factor=1, max_per_channel=1)) == 2


def test_no_recent_and_unknown_metadata():
    old = video(1, 10000, posted=1)
    unknown = video(2, None)
    selection = filters.select_channel([old], days=1, now=1000000)
    assert selection.recent == 0 and selection.videos == [] and selection.median is None
    assert filters.select_channel([unknown], min_views=0).videos == []
    assert filters.select_channel([video(3, 5)], min_views=0, viral_factor=1).recent == 1


def test_script_groups_keep_highest_and_record_channels():
    text = 'Đây là câu chuyện được kể lại với nhiều từ khác nhau trong video này'
    a, b = video(1, 100, 'A', text=text), video(2, 500, 'B', text=text.upper())
    kept, duplicates, notes = filters.dedupe_scripts([a, b], [])
    assert kept == [b] and duplicates == [a]
    assert b.so_kenh == 2 and b.kenh_cung_dang == ['B', 'A']
    assert notes == [f'Bỏ qua (cùng kịch bản với video 500 view của B): {a.url}']


def test_script_matching_history_skips_group():
    text = 'Một câu chuyện tiếng Việt đủ dài để làm kịch bản dùng lại trong nhiều video'
    rows = [video(1, 200, 'A', text=text), video(2, 100, 'B', text=text)]
    kept, duplicates, notes = filters.dedupe_scripts(rows, [
        {'transcript': text, 'taken_on': '2026-10-01', 'page_name': 'C'}])
    assert kept == [] and {v.video_id for v in duplicates} == {'1', '2'}
    assert notes[-1] == f'Bỏ qua (kịch bản đã lấy ngày 01/10/2026 từ C): {rows[0].url}'


def test_fingerprints_strip_accents_and_use_smaller_set():
    assert filters.fingerprint('ĐÂY là lời nói') == filters.fingerprint('day la loi noi')
    assert filters.similarity({'a', 'b'}, {'a', 'b', 'c'}) == 1
    assert filters.similarity(set(), {'a'}) == 0

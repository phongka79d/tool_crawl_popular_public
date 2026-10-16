from contextlib import closing
from datetime import datetime
import pytest
from openpyxl import Workbook, load_workbook
from backend.core.models import Video
from backend.core.normalize import to_vn_datetime, VN_TZ
from backend.services import export_excel as excel

HEADERS = ['STT', 'Kênh', 'Follower kênh', 'Ngày đăng', 'Định dạng', 'Thời lượng (giây)', 'Link bài',
           'Lượt xem', 'Cảm xúc', 'Bình luận', 'Chia sẻ', 'Tổng tương tác', 'View/Follower',
           'Hệ số so trung vị kênh', 'Tỷ lệ tương tác', 'Tỷ lệ share', 'Chủ đề', 'Caption',
           'Nội dung thoại', 'Hook gốc', 'Số kênh cùng đăng', 'Tình trạng', 'Trạng thái', 'Ghi chú']
LINE = 'B (facebook): quét 2 video'


@pytest.fixture
def exported(tmp_path):
    old = Video('old', 'https://example/old', 'a', page_name='A', views=6600000,
                transcript='old speech', taken_on='2026-10-01')
    new = Video('new', 'https://example/new', 'b', page_name='B', page_followers=66000,
                views=66000, reactions=850, comments=0, shares=150, interactions=1000,
                ratio_follow=1, ratio_median=3, engagement=1000/66000, share_rate=150/66000,
                posted_at=1760000000, duration_s=32.5, format='reel', caption='Dòng đầu\nDòng sau',
                transcript='new speech', transcript_clean='Thoại đã sửa', notes=['Ghi chú riêng'],
                so_kenh=2, kenh_cung_dang=['B', 'C'])
    missing = Video('missing', 'https://example/missing', 'c', page_name='C')
    moment = datetime(2026, 10, 16, 12, 30, tzinfo=VN_TZ)
    return excel.export([old, missing, new], [LINE], ['Bỏ qua video', 'không đọc được kênh'], tmp_path,
        channel_stats=[dict(name='B', url='b', followers=66000, scanned=2, recent=2,
                            median=22000, threshold=66000, selected=1, highest_views=66000)],
        run_log=dict(started_at=moment, finished_at=moment, channel_count=3,
                     params=dict(days=14, min_views=50000, viral_factor=3, max_per_channel=10,
                                 formats={'video', 'reel'}), llm='OpenAI / test-model'))


def test_headers_groups_style_and_order(exported):
    with closing(load_workbook(exported)) as workbook:
        assert workbook.sheetnames == ['Chi tiết video', 'Tổng hợp kênh', 'Nhật ký']
        sheet = workbook['Chi tiết video']
        assert [cell.value for cell in sheet[2]] == HEADERS
        assert set(map(str, sheet.merged_cells.ranges)) == {'A1:G1', 'H1:P1', 'Q1:T1', 'U1:X1'}
        for address, title, colour in [('A1', 'Thông tin bài', 'DCEAF3'), ('H1', 'Chỉ số', 'DDF0E8'),
                                     ('Q1', 'Nội dung', 'E6EFF3'), ('U1', 'Theo dõi', 'E8F2EF')]:
            assert sheet[address].value == title
            assert sheet[address].fill.fgColor.rgb.endswith(colour)
        assert [sheet.cell(row, 2).value for row in range(3, 6)] == ['B', 'C', 'A']
        assert sheet['V3'].value == 'Mới' and sheet['V5'].value == 'Đã lấy ngày 01/10'
        assert sheet['A3'].fill.fgColor.rgb.endswith('E2EFDA')
        assert sheet['V3'].fill.fgColor.rgb.endswith('E2EFDA')
        assert not sheet['A5'].fill.fgColor.rgb.endswith('E2EFDA')
        assert sheet['A2'].fill.fgColor.rgb.endswith('234E63') and sheet['A2'].font.bold
        assert sheet['G3'].hyperlink.target == 'https://example/new'
        assert sheet['U3'].value == '2 (B, C)'
        assert sheet.freeze_panes == 'C3' and sheet.auto_filter.ref == 'A2:X5'
        assert sheet.column_dimensions['S'].width == 60 and sheet.column_dimensions['G'].width == 16
        assert sheet['S3'].alignment.wrap_text and sheet['S3'].alignment.vertical == 'top'
        assert [sheet.sheet_properties.tabColor.rgb[-6:] for sheet in workbook] == ['287D8E', '55A58B', '8295A3']


def test_values_formats_missing_and_notes(exported):
    with closing(load_workbook(exported)) as workbook:
        sheet = workbook['Chi tiết video']
        assert [sheet.cell(3, column).value for column in (3, 8, 9, 10, 11, 12)] == [
            '66 nghìn', '66 nghìn', '850', '0', '150', '1 nghìn']
        assert sheet['H5'].value == '6,6 triệu'
        assert sheet['D3'].value == to_vn_datetime(1760000000).replace(tzinfo=None)
        assert sheet['D3'].number_format == 'dd/mm/yyyy hh:mm'
        assert sheet['E3'].value == 'Reel' and sheet['E5'].value == 'Video thường'
        assert sheet['F3'].value == 32.5
        for column, fmt in [(13, '0.0%'), (14, '#,##0.00'), (15, '0.0%'), (16, '0.00%')]:
            assert isinstance(sheet.cell(3, column).value, (float, int))
            assert sheet.cell(3, column).number_format == fmt
        assert sheet['Q3'].value is None and sheet['W3'].value is None
        assert sheet['S3'].value == 'Thoại đã sửa'
        assert sheet['T3'].value == 'Dòng đầu\nnew speech'
        assert sheet['X3'].value == 'Ghi chú riêng\nLời thoại đã được AI sửa'
        assert sheet['X5'].value == 'Bản chép máy, chưa sửa'
        for column in (3, 4, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16):
            assert sheet.cell(4, column).value is None
        log = workbook['Nhật ký']
        coloured = {row[1].value: row[1].font.color for row in log if len(row) > 1 and row[1].value}
        assert coloured['Bỏ qua video'].rgb.endswith('7F7F7F')
        assert coloured['LỖI: không đọc được kênh'].rgb.endswith('C0392B')
        values = {row[0].value: row[1].value for row in log if len(row) > 1}
        assert values['AI cải thiện lời thoại'] == 'OpenAI / test-model'
        assert values['Model chép lời'] == 'faster-whisper small (tiếng Việt)'
        assert values['Lượt xem tối thiểu'] == '50 nghìn'
        summary = workbook['Tổng hợp kênh']
        rows = list(summary.values)
        assert any(row[:8] == ('Kênh', 'Follower', 'Video quét', 'Video trong N ngày', 'View trung vị',
                                'Ngưỡng lấy', 'Video lấy', 'View cao nhất') for row in rows)
        assert any(row[:8] == ('B', '66 nghìn', '2', '2', '22 nghìn', '66 nghìn', '1', '66 nghìn') for row in rows)
        assert any(row[0] == 'Top 10 lượt xem' for row in rows)


def test_new_summary(exported):
    result = excel.read_summary(exported)
    assert (result['total'], result['new'], result['taken_before']) == (3, 2, 1)
    assert result['views_total'] == 6666000
    assert result['top'][0]['url'] == 'https://example/old'
    assert result['top'][1]['transcript'] == 'Thoại đã sửa'
    assert result['scan_lines'] == [LINE]
    assert result['notes'] == ['Bỏ qua video']
    assert result['errors'] == ['LỖI: không đọc được kênh']


def test_legacy_summary(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Nội dung'
    sheet.append(['STT', 'Chủ đề', 'Nội dung thoại', 'Trạng thái', 'Link video mẫu', 'Kênh',
                  'Lượt xem', 'Ngày đăng', 'Số kênh cùng đăng', 'Tình trạng'])
    sheet.append([1, 'Chủ đề cũ', 'Thoại cũ', '', 'https://example/old', 'Kênh cũ',
                  '6,6 triệu', '01/10/2026', '1', 'Đã lấy ngày 01/10'])
    sheet.append([2, '', 'Thoại mới', '', 'https://example/new', 'Kênh cũ', '850', '', '1', 'Mới'])
    scan = workbook.create_sheet('Tình hình quét')
    for line in ['Kết quả quét từng kênh', LINE, 'Bỏ qua cũ', 'LỖI: cũ']:
        scan.append([line])
    path = tmp_path / 'legacy.xlsx'
    workbook.save(path)
    workbook.close()
    result = excel.read_summary(path)
    assert result['total'] == 2 and result['views_total'] == 6600850
    assert result['new'] == result['taken_before'] == 1
    assert result['channels'] == [{'name': 'Kênh cũ', 'count': 2}]
    assert result['top'][0] == dict(stt=1, topic='Chủ đề cũ', transcript='Thoại cũ', channel='Kênh cũ',
        views=6600000, views_text='6,6 triệu', posted='01/10/2026', url='https://example/old', status='Đã lấy ngày 01/10')
    assert result['scan_lines'] == [LINE] and result['notes'] == ['Bỏ qua cũ'] and result['errors'] == ['LỖI: cũ']


def test_collision_formula_safety_and_disabled_ai(tmp_path):
    video = Video('1', 'https://example/1', 'a', page_name='@name',
                  caption='=HYPERLINK("bad")', transcript=' =SUM(A1:A2)\x01', notes=['+formula'])
    first = excel.export([video], ['=formula'], ['Bỏ qua video'], tmp_path)
    second = excel.export([video], output_dir=tmp_path)
    assert first != second and '(lần 2)' in second.name and first.exists()
    with closing(load_workbook(first)) as workbook:
        sheet = workbook['Chi tiết video']
        for address in ('B3', 'R3', 'S3', 'T3', 'X3'):
            assert sheet[address].value.startswith("'") and sheet[address].data_type == 's'
        assert '\x01' not in sheet['S3'].value
        assert any(row[1] == 'Không bật' for row in workbook['Nhật ký'].values)


def test_hook_limits_and_fallbacks():
    assert excel.first_lines_hook('x' * 250 + '\nignored', ' '.join(map(str, range(40)))) == (
        'x' * 200 + '\n' + ' '.join(map(str, range(30))))
    assert excel.first_lines_hook('', 'raw') == 'raw'
    assert excel.first_lines_hook('caption', '') == 'caption'


@pytest.mark.parametrize('value,expected', [(6600000, '6,6 triệu'), (1000000, '1,0 triệu'),
    (66000, '66 nghìn'), (165000, '165 nghìn'), (12, '12'), (0, '0'), (None, '')])
def test_view_format(value, expected):
    assert excel.format_views(value) == expected


@pytest.mark.parametrize('kind', ['corrupt', 'unknown', 'missing_headers'])
def test_invalid_workbook(tmp_path, kind):
    path = tmp_path / 'invalid.xlsx'
    if kind == 'corrupt':
        path.write_text('not a workbook')
    else:
        workbook = Workbook()
        if kind == 'missing_headers':
            workbook.active.title = 'Chi tiết video'
        workbook.save(path)
        workbook.close()
    with pytest.raises(ValueError, match='Excel'):
        excel.read_summary(path)

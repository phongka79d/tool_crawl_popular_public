"""Old public-tool workbook format and tolerant library summaries."""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from backend.core import config
from backend.core.models import Video
from backend.core.normalize import parse_count, to_vn_datetime, VN_TZ

HEADERS = ['STT', 'Chủ đề', 'Nội dung thoại', 'Trạng thái', 'Link video mẫu', 'Kênh',
           'Lượt xem', 'Ngày đăng', 'Số kênh cùng đăng', 'Tình trạng']
WIDTHS = [6, 32, 90, 12, 45, 22, 14, 12, 22, 16]


def format_views(value: int | float | None) -> str:
    if not value:
        return ''
    if value >= 1000000:
        return f'{value / 1000000:.1f}'.replace('.', ',') + ' triệu'
    if value >= 1000:
        return f'{round(value / 1000)} nghìn'
    return str(value)


def _safe(value):
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub('', value)
    if value.lstrip().startswith(('=', '+', '-', '@')):
        value = "'" + value
    return value[:32767]


def export(videos: list[Video], scan_lines: list[str] | None = None,
           notes: list[str] | None = None, output_dir: Path | None = None) -> Path:
    directory = Path(output_dir) if output_dir is not None else config.OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    base = datetime.now(VN_TZ).strftime('%Y-%m-%d')
    number = 1
    while True:
        suffix = '' if number == 1 else f' (lần {number})'
        path = directory / f'{base}{suffix}.xlsx'
        try:
            handle = path.open('xb')
            break
        except FileExistsError:
            number += 1
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Nội dung'
    sheet.append(HEADERS)
    for cell, width in zip(sheet[1], WIDTHS):
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='1F4E78')
        cell.alignment = Alignment(horizontal='center', vertical='center')
        sheet.column_dimensions[cell.column_letter].width = width
    ordered = sorted(videos, key=lambda v: (bool(v.taken_on), -(v.views or 0)))
    for index, video in enumerate(ordered, 1):
        status = ('Đã lấy ngày ' + datetime.strptime(video.taken_on, '%Y-%m-%d').strftime('%d/%m')
                  if video.taken_on else 'Mới')
        channels = str(video.so_kenh)
        if video.so_kenh > 1:
            channels += ' (' + ', '.join(video.kenh_cung_dang) + ')'
        sheet.append([_safe(value) for value in [index, '', video.transcript_clean or video.transcript, '', video.url,
                     video.page_name, format_views(video.views),
                     to_vn_datetime(video.posted_at).strftime('%d/%m/%Y') if video.posted_at is not None else '',
                     channels, status]])
        row = sheet.max_row
        for cell in sheet[row]:
            cell.alignment = Alignment(wrap_text=True, vertical='top')
        if video.url.startswith(('https://', 'http://')):
            sheet.cell(row, 5).hyperlink = video.url
            sheet.cell(row, 5).font = Font(color='0000FF', underline='single')
        if not video.taken_on:
            for column in (1, 10):
                sheet.cell(row, column).fill = PatternFill('solid', fgColor='E2EFDA')
    sheet.freeze_panes = 'A2'
    scan = workbook.create_sheet('Tình hình quét')
    scan.column_dimensions['A'].width = 140
    scan.append(['Kết quả quét từng kênh'])
    scan['A1'].font = Font(bold=True)
    for line in scan_lines or []:
        scan.append([_safe(line)])
    for note in notes or []:
        skipped = note.startswith('Bỏ qua')
        scan.append([_safe(note if skipped or note.startswith('LỖI:') else 'LỖI: ' + note)])
        scan.cell(scan.max_row, 1).font = Font(color='7F7F7F' if skipped else 'C0392B')
    for row in scan:
        row[0].alignment = Alignment(wrap_text=True, vertical='top')
    try:
        with handle:
            workbook.save(handle)
    except BaseException:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()
    return path


def read_summary(path: str | Path) -> dict:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError('Không đọc được tệp Excel nội dung.') from exc
    try:
        if 'Nội dung' not in workbook.sheetnames:
            raise ValueError('Tệp Excel không đúng định dạng nội dung.')
        rows = workbook['Nội dung'].iter_rows(values_only=True)
        header = list(next(rows, ()))
        if any(name not in header for name in HEADERS):
            raise ValueError('Tệp Excel thiếu cột nội dung bắt buộc.')
        indices = {name: header.index(name) for name in HEADERS}
        entries, channels = [], Counter()
        new = taken = total_views = 0
        for row in rows:
            if not any(value is not None for value in row):
                continue
            def value(name):
                index = indices[name]
                return row[index] if index < len(row) else None
            views_text = str(value('Lượt xem') or '')
            views = parse_count(views_text)
            status = str(value('Tình trạng') or '')
            channel = str(value('Kênh') or '')
            channels[channel] += 1
            new += status.strip().casefold() == 'mới'
            taken += status.startswith('Đã lấy')
            total_views += views or 0
            posted = value('Ngày đăng')
            entries.append({'stt': value('STT'), 'topic': str(value('Chủ đề') or ''),
                            'transcript': str(value('Nội dung thoại') or ''), 'channel': channel,
                            'views': views, 'views_text': views_text,
                            'posted': posted.strftime('%d/%m/%Y') if isinstance(posted, datetime) else str(posted or ''),
                            'url': str(value('Link video mẫu') or ''), 'status': status})
        scan_lines, notes, errors = [], [], []
        if 'Tình hình quét' in workbook.sheetnames:
            for row in workbook['Tình hình quét'].iter_rows(min_row=2, values_only=True):
                line = str(row[0] or '').strip()
                if not line:
                    continue
                if line.startswith('Bỏ qua'):
                    notes.append(line)
                elif line.startswith('LỖI:'):
                    errors.append(line)
                else:
                    scan_lines.append(line)
        return {'total': len(entries), 'new': new, 'taken_before': taken, 'views_total': total_views,
                'channels': [{'name': name, 'count': count} for name, count in channels.most_common()],
                'top': sorted(entries, key=lambda entry: -(entry['views'] or 0))[:10],
                'scan_lines': scan_lines, 'notes': notes, 'errors': errors}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Tệp Excel không đúng định dạng nội dung.') from exc
    finally:
        workbook.close()

"""Facebook → channel median filter → local speech → script history → Excel."""
from __future__ import annotations
import argparse
import logging
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Callable
from backend.collectors.facebook import FacebookScanner, page_url_problem
from backend.collectors import transcript, ytdlp
from backend.core import config, db, keys
from backend.core.applog import redact, protect_key
from backend.core.errors import ServiceError
from backend.core.models import Video
from backend.core.normalize import VN_TZ
from backend.services import filters, export_excel, llm_client

logger = logging.getLogger(__name__)


@dataclass
class RunParams:
    days: int = 14
    formats: frozenset[str] = frozenset({'video', 'reel'})
    min_views: int = 50000
    viral_factor: float = 3.0
    max_per_channel: int = 10

    def __post_init__(self):
        if self.days < 1 or self.min_views < 0 or not 0 < self.viral_factor < float('inf') or self.max_per_channel < 1:
            raise ValueError('Ngưỡng quét không hợp lệ.')
        if not self.formats or not self.formats <= {'video', 'reel'}:
            raise ValueError('Chỉ hỗ trợ video và reel Facebook.')


@dataclass
class Progress:
    stage: str
    page_index: int = 0
    page_total: int = 0
    page_url: str = ''
    message: str = ''
    done: bool = False
    error: str | None = None
    step: int = 0
    steps: int = 0
    transient: bool = False
    page_name: str = ''
    found: int | None = None
    passed: int | None = None


def run(params: RunParams, settings: dict | None = None, stop: threading.Event | None = None,
        on_progress: Callable[[Progress], None] | None = None) -> Path | None:
    settings = settings if settings is not None else config.load_settings()
    stop = stop if stop is not None else threading.Event()
    config.ensure_dirs()
    db.init_db()
    run_id = db.start_run(asdict(params))
    channels = config.load_lines('config/channels.txt')
    candidates, summaries, notes = [], [], []
    result = None
    index, page_url, page_name = 0, '', ''
    today = datetime.now(VN_TZ).strftime('%Y-%m-%d')

    def emit(stage, message, **kwargs):
        if on_progress:
            on_progress(Progress(stage=stage, page_index=index, page_total=len(channels),
                                 page_url=page_url, page_name=page_name, message=redact(str(message)), **kwargs))

    def error(exc):
        message = redact(str(exc))
        notes.append(message)
        logger.warning('%s', message)
        emit('error', message, error=message)

    try:
        llm = settings.get('llm', {})
        llm_key = keys.get_key() if llm.get('base_url') and llm.get('model') else None
        if llm_key:
            protect_key(llm_key)
            try:
                llm_client.check_key(llm['base_url'], llm_key, llm['model'])
            except Exception as exc:
                error('LỖI: Không cải thiện được lời thoại: ' + redact(str(exc)))
                llm_key = None
        seen = set()
        try:
            emit('scan', 'Mở trình duyệt quét Facebook…')
            with FacebookScanner(hidden=True, settings=settings) as scanner:
                scanner.check_login()
                for index, page_url in enumerate(channels, 1):
                    if stop.is_set():
                        break
                    page_name = page_url
                    problem = page_url_problem(page_url)
                    if problem:
                        error(problem)
                        emit('scan', problem, found=0, passed=0)
                        continue
                    page_items = []
                    fatal = None
                    try:
                        page = scanner.get_page_info(page_url)
                        page_name = page.name or page_url
                        db.upsert_page(page)
                        emit('scan', f'Đang quét {page_name}…')
                        try:
                            rows = scanner.scan_page(page_url, days=params.days, formats=params.formats,
                                max_videos=settings['scan']['max_videos_per_page'], stop_event=stop,
                                on_progress=lambda text, transient=False: emit('scan', text, transient=transient))
                        except ServiceError as exc:
                            rows = getattr(exc, 'partial_rows', [])
                            fatal = exc
                        allowed = {field.name for field in fields(Video)}
                        for row in rows:
                            values = {key: value for key, value in row.items() if key in allowed}
                            values.update(page_url=page_url, page_name=page_name, page_followers=page.followers)
                            video = Video(**values)
                            if video.video_id in seen or video.format not in params.formats or video.is_live:
                                continue
                            seen.add(video.video_id)
                            db.upsert_video(video)
                            page_items.append(video)
                        notes.extend(redact(str(message)) for message in getattr(scanner, 'scan_errors', []))
                    except ServiceError as exc:
                        fatal = exc
                    except Exception as exc:
                        error(exc)
                    # Partial rows still get the date/view check, even when scrolling was interrupted.
                    for video in page_items:
                        if video.posted_at is None or video.views is None:
                            try:
                                ytdlp.fill_missing(video)
                                db.upsert_video(video)
                            except Exception as exc:
                                error(exc)
                    selected = filters.select_channel(page_items, params.days, params.min_views,
                                                      params.viral_factor, params.max_per_channel)
                    candidates.extend(selected.videos)
                    baseline = export_excel.format_views(selected.median) if selected.median is not None else '?'
                    factor = f'{params.viral_factor:g}'
                    summaries.append(f'{page_name} (facebook): quét {len(page_items)} video, '
                        f'{selected.recent} video trong {params.days} ngày, mức thường {baseline} view, '
                        f'lấy {len(selected.videos)} video viral (ngưỡng ≥ x{factor} và ≥ {export_excel.format_views(params.min_views)})')
                    if not selected.recent:
                        notes.append(f'{page_name}: không có video nào đăng trong {params.days} ngày gần đây')
                    emit('scan', summaries[-1], found=len(page_items), passed=len(selected.videos))
                    if fatal is not None:
                        raise fatal
                    if index < len(channels) and not stop.is_set():
                        scanner.polite_page_pause(stop_event=stop,
                            on_tick=lambda left: emit('scan', f'Nghỉ giữa kênh: còn {left} giây', transient=True))
        except Exception as exc:
            error(exc)
        reused, fresh = [], []
        for video in candidates:
            previous = db.get_taken(video.video_id)
            if previous:
                if previous['status'] == 'taken':
                    video.transcript = previous['transcript'] or ''
                    video.transcript_clean = previous.get('transcript_clean') or ''
                    video.taken_on = previous['taken_on']
                    reused.append(video)
                continue
            fresh.append(video)
        transcriber = transcript.Transcriber()
        spoken = []
        for number, video in enumerate(fresh, 1):
            if stop.is_set():
                break
            page_url, page_name = video.page_url, video.page_name
            emit('transcribe', f'Chép lời video {number}/{len(fresh)}…', step=number - 1, steps=len(fresh))
            try:
                text, status = transcript.get_transcript(video, transcriber, stop)
                if not status:
                    break
                if status == transcript.NO_SPEECH:
                    notes.append(f'Bỏ qua (không có lời nói): {video.url}')
                    db.save_taken(video, 'no_speech', today)
                else:
                    spoken.append(video)
                emit('transcribe', f'Đã chép lời video {number}/{len(fresh)}.', step=number, steps=len(fresh))
            except Exception as exc:
                error(exc)
        kept, duplicates, skipped = filters.dedupe_scripts(spoken, db.list_taken(),
                                                          settings['scan'].get('dedupe_threshold', 0.5))
        notes.extend(skipped)
        for video in duplicates:
            db.save_taken(video, 'duplicate_script', today)
        if llm_key:
            enhanced = []
            batches = (len(kept) + 7) // 8
            for offset in range(0, len(kept), 8):
                if stop.is_set():
                    enhanced.extend(kept[offset:])
                    break
                batch = kept[offset:offset + 8]
                number = offset // 8 + 1
                emit('enhance', f'Cải thiện lời thoại {number}/{batches}…', step=number - 1, steps=batches)
                try:
                    answers = llm_client.enhance_batch(llm['base_url'], llm_key, llm['model'], batch)
                    for video in batch:
                        answer = answers[video.video_id]
                        if not answer['co_loi_noi']:
                            notes.append(f'Bỏ qua (nhạc / bài hát, không phải lời nói): {video.url}')
                            db.save_taken(video, 'no_speech', today)
                        else:
                            video.transcript_clean = redact(answer['thoai'])
                            enhanced.append(video)
                except Exception as exc:
                    error('LỖI: Không cải thiện được lời thoại: ' + redact(str(exc)))
                    enhanced.extend(batch)
                emit('enhance', f'Đã cải thiện lời thoại {number}/{batches}.', step=number, steps=batches)
            kept = enhanced
        if stop.is_set():
            notes.append('Đã dừng theo yêu cầu; xuất dữ liệu đã có.')
        if not summaries and not kept and not reused:
            emit('done', 'Đã kết thúc, chưa có dữ liệu để xuất.', done=True)
            return None
        emit('export', 'Đang xuất Excel…')
        result = export_excel.export(kept + reused, summaries, notes)
        for video in kept:
            db.save_taken(video, 'taken', today)
        emit('done', f'Đã xuất {len(kept) + len(reused)} video: {result.name}', done=True)
        return result
    finally:
        db.finish_run(run_id, {'scan_lines': summaries, 'notes': notes,
                               'output': str(result) if result else None, 'stopped': stop.is_set()})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Quét video viral Facebook và chép lời tiếng Việt.')
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--min-views', type=int, default=50000)
    parser.add_argument('--viral-factor', type=float, default=3)
    parser.add_argument('--max-per-channel', type=int, default=10)
    parser.add_argument('--formats', default='video,reel')
    args = parser.parse_args(argv)
    try:
        params = RunParams(args.days, frozenset(part.strip() for part in args.formats.split(',') if part.strip()),
                           args.min_views, args.viral_factor, args.max_per_channel)
    except ValueError as exc:
        parser.error(str(exc))
    stop = threading.Event()
    import signal
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    result = run(params, stop=stop, on_progress=lambda progress: print(progress.message))
    return 0 if result is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())

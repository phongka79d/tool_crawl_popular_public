"""Facebook → channel median filter → local speech → script history → Excel."""
from __future__ import annotations
import argparse
import logging
import threading
import queue
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
    channels = config.load_lines(config.CHANNELS_FILE)
    summaries, notes, channel_stats = [], [], []
    reused, spoken, rejected = [], [], set()
    pending = queue.Queue()
    progress_lock = threading.RLock()
    completed, known = 0, 0
    worker = None
    result = None
    index, page_url, page_name = 0, '', ''
    started_at = datetime.now(VN_TZ)
    today = started_at.strftime('%Y-%m-%d')

    def emit(stage, message, context=None, **kwargs):
        with progress_lock:
            number, url, name = context if context is not None else (index, page_url, page_name)
            if on_progress:
                on_progress(Progress(stage=stage, page_index=number, page_total=len(channels),
                    page_url=url, page_name=name, message=redact(str(message)), **kwargs))

    def error(exc, context=None):
        message = redact(str(exc))
        notes.append(message)
        logger.warning('%s', message)
        emit('error', message, context=context, error=message)

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
        history = db.list_taken()

        def process_channels():
            # Only plain Video data crosses this queue; Playwright stays on the scanner thread.
            nonlocal completed
            transcriber = transcript.Transcriber()
            while True:
                task = pending.get()
                if task is None:
                    return
                context, videos = task
                channel_spoken = []
                for video in videos:
                    with progress_lock:
                        emit('transcribe', f'Chép lời video {completed + 1}/{known}…',
                             context=context, step=completed, steps=known)
                    try:
                        previous = db.get_taken(video.video_id)
                        if previous:
                            if previous['status'] == 'taken':
                                video.transcript = previous['transcript'] or ''
                                video.transcript_clean = previous.get('transcript_clean') or ''
                                video.taken_on = previous['taken_on']
                                reused.append(video)
                        else:
                            if stop.is_set():
                                continue
                            _, status = transcript.get_transcript(video, transcriber, stop)
                            if not status:
                                continue
                            if status == transcript.NO_SPEECH:
                                notes.append(f'Bỏ qua (không có lời nói): {video.url}')
                                db.save_taken(video, 'no_speech', today)
                            else:
                                spoken.append(video)
                                channel_spoken.append(video)
                    except Exception as exc:
                        error(exc, context)
                    with progress_lock:
                        completed += 1
                        emit('transcribe', f'Đã xử lý {completed}/{known} video.',
                             context=context, step=completed, steps=known)
                if not llm_key:
                    continue
                # Avoid paying to enhance scripts already present in history. Final grouping
                # still runs once, globally, after every channel has finished transcription.
                threshold = settings['scan'].get('dedupe_threshold', 0.5)
                eligible = [v for v in channel_spoken if not any(
                    filters.similarity(filters.fingerprint(v.transcript),
                                       filters.fingerprint(old['transcript'])) >= threshold for old in history)]
                for offset in range(0, len(eligible), 8):
                    if stop.is_set():
                        break
                    batch = eligible[offset:offset + 8]
                    emit('enhance', 'Cải thiện lời thoại…', context=context, step=completed, steps=known)
                    try:
                        answers = llm_client.enhance_batch(llm['base_url'], llm_key, llm['model'], batch)
                        for video in batch:
                            answer = answers[video.video_id]
                            if not answer['co_loi_noi']:
                                notes.append(f'Bỏ qua (nhạc / bài hát, không phải lời nói): {video.url}')
                                rejected.add(video.video_id)
                                db.save_taken(video, 'no_speech', today)
                            else:
                                video.transcript_clean = redact(answer['thoai'])
                    except Exception as exc:
                        error('LỖI: Không cải thiện được lời thoại: ' + redact(str(exc)), context)
                emit('transcribe', f'Đã xử lý {completed}/{known} video.',
                     context=context, step=completed, steps=known)

        worker = threading.Thread(target=process_channels, name='video-transcribe')
        worker.start()
        seen = set()
        try:
            emit('scan', 'Mở trình duyệt quét Facebook…')
            with FacebookScanner(hidden=True, settings=settings) as scanner:
                scanner.check_login()
                for index, page_url in enumerate(channels, 1):
                    if stop.is_set():
                        break
                    page_name = page_url
                    followers = None
                    problem = page_url_problem(page_url)
                    if problem:
                        error(problem)
                        emit('scan', problem, found=0, passed=0)
                        channel_stats.append(dict(url=page_url, name=page_name, followers=None,
                            scanned=0, recent=0, median=None, threshold=None, selected=0, highest_views=None))
                        continue
                    page_items = []
                    fatal = None
                    try:
                        page = scanner.get_page_info(page_url)
                        page_name = page.name or page_url
                        followers = page.followers
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
                        # Old videos cannot affect the recent median or selection. Low-view
                        # undated videos MUST still be backfilled: recency affects the median.
                        if stop.is_set():
                            break
                        if (video.posted_at is None or video.views is None) and not (
                                video.posted_at is not None and
                                filters.is_older_than(video.posted_at, params.days)):
                            try:
                                ytdlp.fill_missing(video)
                                db.upsert_video(video)
                            except Exception as exc:
                                error(exc)
                    selected = filters.select_channel(page_items, params.days, params.min_views,
                                                      params.viral_factor, params.max_per_channel)
                    with progress_lock:
                        known += len(selected.videos)
                    channel_stats.append(dict(url=page_url, name=page_name, followers=followers,
                        scanned=len(page_items), recent=selected.recent, median=selected.median,
                        threshold=selected.threshold, selected=len(selected.videos),
                        highest_views=max((video.views for video in page_items if video.views is not None), default=None)))
                    baseline = export_excel.format_views(selected.median) if selected.median is not None else '?'
                    factor = f'{params.viral_factor:g}'
                    summaries.append(f'{page_name} (facebook): quét {len(page_items)} video, '
                        f'{selected.recent} video trong {params.days} ngày, mức thường {baseline} view, '
                        f'lấy {len(selected.videos)} video viral (ngưỡng ≥ x{factor} và ≥ {export_excel.format_views(params.min_views)})')
                    if not selected.recent:
                        notes.append(f'{page_name}: không có video nào đăng trong {params.days} ngày gần đây')
                    emit('scan', summaries[-1], found=len(page_items), passed=len(selected.videos))
                    # scan_page's finally exports cookies before these plain rows are queued.
                    pending.put(((index, page_url, page_name), selected.videos))
                    if fatal is not None:
                        raise fatal
                    if index < len(channels) and not stop.is_set():
                        scanner.polite_page_pause(stop_event=stop,
                            on_tick=lambda left: emit('scan', f'Nghỉ giữa kênh: còn {left} giây', transient=True))
        except Exception as exc:
            error(exc)
        finally:
            pending.put(None)
            worker.join()
            worker = None
        kept, duplicates, skipped = filters.dedupe_scripts(
            [v for v in spoken if v.video_id not in rejected], history,
            settings['scan'].get('dedupe_threshold', 0.5))
        notes.extend(skipped)
        for video in duplicates:
            db.save_taken(video, 'duplicate_script', today)
        if stop.is_set():
            notes.append('Đã dừng theo yêu cầu; xuất dữ liệu đã có.')
        if not summaries and not kept and not reused:
            emit('done', 'Đã kết thúc, chưa có dữ liệu để xuất.', done=True)
            return None
        emit('export', 'Đang xuất Excel…')
        result = export_excel.export(kept + reused, summaries, notes, channel_stats=channel_stats,
            run_log=dict(started_at=started_at, finished_at=datetime.now(VN_TZ),
                         channel_count=len(channels), params=asdict(params),
                         llm=redact(f"{llm.get('provider') or llm.get('base_url')} / {llm['model']}") if llm_key else None))
        for video in kept:
            db.save_taken(video, 'taken', today)
        emit('done', f'Đã xuất {len(kept) + len(reused)} video: {result.name}', done=True)
        return result
    finally:
        if worker is not None:
            pending.put(None)
            worker.join()
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

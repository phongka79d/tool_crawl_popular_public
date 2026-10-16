"""Local Vietnamese transcription; PyAV decodes downloaded audio without ffmpeg."""
from __future__ import annotations
import tempfile
from pathlib import Path
import threading
from backend.collectors import ytdlp
from backend.core import config, db
from backend.core.models import Video

OK = 'ok'
NO_SPEECH = 'no_speech'
FAILED = 'failed'


class Transcriber:
    """One lazily loaded CPU model, owned by one pipeline run."""

    def __init__(self):
        self._model = None

    def transcribe(self, path) -> str:
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel('small', device='cpu', compute_type='int8',
                                       download_root=str(config.DATA_DIR / 'models'))
        segments, _ = self._model.transcribe(str(path), language='vi', vad_filter=True)
        return ' '.join(segment.text.strip() for segment in segments).strip()


def get_transcript(video: Video, transcriber: Transcriber | None = None,
                   stop: threading.Event | None = None) -> tuple[str, str]:
    cached = db.get_transcript(video.video_id)
    if cached and cached[1] in (OK, NO_SPEECH):
        video.transcript, video.transcript_status = cached
        video.transcript_language = 'vi'
        return cached
    if stop is not None and stop.is_set():
        return '', ''
    transcriber = transcriber or Transcriber()
    with tempfile.TemporaryDirectory(prefix='speech_', dir=config.DATA_DIR) as temporary:
        audio = ytdlp.download_audio(video.url, Path(temporary))
        if audio is None:
            raise RuntimeError(f'Không tải được âm thanh: {video.url}')
        if stop is not None and stop.is_set():
            return '', ''
        text = transcriber.transcribe(audio)
    status = OK if len(text) >= 30 else NO_SPEECH
    video.transcript, video.transcript_status, video.transcript_language = text, status, 'vi'
    db.save_transcript(video.video_id, text, status)
    return text, status

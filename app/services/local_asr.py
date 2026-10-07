"""Offline SenseVoice recognition; no audio or credentials go to a cloud API."""

from pathlib import Path
import os
import re
import subprocess
from threading import Lock

from ..config import Config


_recognizer = None
_recognizer_lock = Lock()


class AudioDecodeError(ValueError):
    """The uploaded recording is incomplete or cannot be decoded."""


class ASRUnavailableError(RuntimeError):
    """A required local recognition component is missing."""


def _ffmpeg_environment():
    # Nix Python needs its own C++ libraries, but system ffmpeg must use the
    # system libraries. Change only the child environment, never os.environ.
    environment = os.environ.copy()
    environment.pop('LD_LIBRARY_PATH', None)
    return environment


def _get_recognizer():
    """Load prepared weights once per worker, under the inference lock."""
    global _recognizer
    if _recognizer is None:
        model_dir = Path(Config.ASR_MODEL_DIR).expanduser()
        model_path = model_dir / 'model.int8.onnx'
        tokens_path = model_dir / 'tokens.txt'
        if not model_path.is_file() or not tokens_path.is_file():
            raise ASRUnavailableError('本地语音模型未准备，请运行 python scripts/prepare_local_asr.py')
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ASRUnavailableError('本地语音识别依赖未安装，请安装 requirements.txt') from exc
        _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            language=Config.ASR_LANGUAGE,
            use_itn=True,
            num_threads=Config.ASR_NUM_THREADS,
            provider='cpu',
        )
    return _recognizer


def transcribe_local_audio(audio_file_path):
    """Decode browser audio locally and recognize in bounded 30-second chunks."""
    import numpy as np
    from pydub import AudioSegment

    try:
        decoded = subprocess.run(
            ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
             '-i', str(audio_file_path), '-vn', '-f', 's16le', '-acodec', 'pcm_s16le',
             '-ar', '16000', '-ac', '1', 'pipe:1'],
            env=_ffmpeg_environment(), capture_output=True, check=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise ASRUnavailableError('录音解码组件 ffmpeg/ffprobe 不可用，请检查服务进程的 PATH') from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if exc.stderr:
            exc.add_note(exc.stderr.decode('utf-8', errors='replace')[:2000])
        raise AudioDecodeError('录音不完整或格式无法解码，请重新按住说话录音') from exc
    audio = AudioSegment(data=decoded.stdout, sample_width=2, frame_rate=16000, channels=1)
    if not len(audio) or audio.rms == 0:
        return ''

    texts = []
    # Serialize CPU inference to avoid concurrent model initialization and spikes.
    with _recognizer_lock:
        recognizer = _get_recognizer()
        for offset in range(0, len(audio), 30000):
            chunk = audio[offset:offset + 30000]
            if chunk.rms == 0:
                continue
            samples = np.asarray(chunk.get_array_of_samples(), dtype=np.float32) / 32768.0
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            text = re.sub(r'<\|[^|]*\|>', '', stream.result.text).strip()
            if text:
                texts.append(text)
    return ' '.join(texts)

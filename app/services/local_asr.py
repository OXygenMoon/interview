"""Offline SenseVoice recognition; no audio or credentials go to a cloud API."""

from pathlib import Path
import re
from threading import Lock

from ..config import Config


_recognizer = None
_recognizer_lock = Lock()


def _get_recognizer():
    """Load prepared weights once per worker, under the inference lock."""
    global _recognizer
    if _recognizer is None:
        model_dir = Path(Config.ASR_MODEL_DIR).expanduser()
        model_path = model_dir / 'model.int8.onnx'
        tokens_path = model_dir / 'tokens.txt'
        if not model_path.is_file() or not tokens_path.is_file():
            raise RuntimeError('本地语音模型未准备，请运行 python scripts/prepare_local_asr.py')
        import sherpa_onnx
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

    audio = AudioSegment.from_file(audio_file_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
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

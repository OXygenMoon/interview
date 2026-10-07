"""Prepare the pinned offline SenseVoice model once on each deployment host."""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

from dotenv import dotenv_values
import requests


ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09'
MODEL_URL = (
    'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
    + MODEL_NAME + '.tar.bz2'
)
# Digest published by the sherpa-onnx GitHub release asset.
MODEL_SHA256 = '7305f7905bfcf77fa0b39388a313f3da35c68d971661a65475b56fb2162c8e63'


def prepare_model(destination):
    destination = Path(destination).expanduser().resolve()
    if all((destination / name).is_file() for name in ('model.int8.onnx', 'tokens.txt')):
        print(f'Local ASR model already prepared: {destination}')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        archive_path = Path(temporary) / 'model.tar.bz2'
        digest = hashlib.sha256()
        print('Downloading pinned SenseVoice model (~158 MiB)...', flush=True)
        with requests.get(MODEL_URL, stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            with archive_path.open('wb') as archive:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    archive.write(block)
                    digest.update(block)
        if digest.hexdigest() != MODEL_SHA256:
            raise RuntimeError('SenseVoice model checksum mismatch')

        staged = Path(temporary) / 'prepared'
        staged.mkdir()
        with tarfile.open(archive_path, 'r:bz2') as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                path = PurePosixPath(member.name)
                if not path.parts or path.parts[0] != MODEL_NAME:
                    continue
                relative = PurePosixPath(*path.parts[1:])
                allowed = str(relative) in ('model.int8.onnx', 'tokens.txt', 'LICENSE')
                allowed = allowed or (
                    len(relative.parts) == 2 and relative.parts[0] == 'test_wavs'
                    and relative.suffix == '.wav'
                )
                if not allowed:
                    continue
                output = staged / str(relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open('wb') as target:
                    shutil.copyfileobj(source, target)
        for name in ('model.int8.onnx', 'tokens.txt'):
            if not (staged / name).is_file():
                raise RuntimeError(f'Model archive is missing {name}')
        destination.mkdir(parents=True, exist_ok=True)
        for source in staged.rglob('*'):
            if source.is_file():
                target = destination / source.relative_to(staged)
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)
    print(f'Local ASR model ready: {destination}')


def main():
    import os
    import sys
    from dotenv import load_dotenv
    values = dotenv_values(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', default=os.environ.get(
        'ASR_MODEL_DIR', values.get('ASR_MODEL_DIR') or ROOT / '.local' / 'asr' / 'sensevoice',
    ))
    parser.add_argument('--check', action='store_true', help='Check local decoding and recognition without downloading')
    args = parser.parse_args()
    if args.check:
        load_dotenv(ROOT / '.env')
        sys.path.insert(0, str(ROOT))
        try:
            for executable in ('ffmpeg', 'ffprobe'):
                if not shutil.which(executable):
                    raise RuntimeError(f'{executable} is missing from the service PATH')
            from app.config import Config
            from app.services.local_asr import _ffmpeg_environment, _get_recognizer, _recognizer_lock, transcribe_local_audio
            Config.ASR_MODEL_DIR = str(Path(args.model_dir).expanduser().resolve())
            with _recognizer_lock:
                _get_recognizer()
            sample = Path(Config.ASR_MODEL_DIR) / 'test_wavs' / 'zh.wav'
            if sample.is_file():
                with tempfile.TemporaryDirectory() as temporary:
                    recording = Path(temporary) / 'check.webm'
                    subprocess.run(
                        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                         '-i', str(sample), '-acodec', 'libopus', str(recording)],
                        env=_ffmpeg_environment(), capture_output=True, check=True, timeout=30,
                    )
                    if not transcribe_local_audio(str(recording)).strip():
                        raise RuntimeError('Recognition returned an empty transcript for the speech sample')
                print('Browser WebM decoding and speech recognition: OK')
            else:
                print('Model loaded; speech sample missing, end-to-end recognition not checked')
            print(f'Local ASR ready: {Config.ASR_MODEL_DIR}')
        except Exception as exc:
            parser.exit(1, f'Local ASR check failed: {exc}\n')
        return
    prepare_model(args.model_dir)


if __name__ == '__main__':
    main()

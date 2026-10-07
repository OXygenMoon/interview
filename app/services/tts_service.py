import base64
import re
import uuid
import requests
import os
import time
import json
import logging
import wave
import websocket
from ..config import Config
from .realtime_voice import connect_provider, resolve_realtime_voice, MAX_AUDIO_BYTES


def text_to_speech(text, output_dir, specific_voice=None):
    """
    基于官方 API 文档实现的火山引擎 TTS
    """
    if Config.VOLC_API_KEY:
        if not Config.VOLC_TTS_RESOURCE_ID:
            return _text_to_speech_realtime(text, output_dir, specific_voice)
        return _text_to_speech_v3(text, output_dir, specific_voice)
    try:
        # 1. 准备目录和文件名
        os.makedirs(output_dir, exist_ok=True)
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        file_path = os.path.join(output_dir, filename)

        print(f"正在调用火山引擎: {text[:15]}...")
        start_time = time.time()

        # 2. 准备参数
        # 接口地址 (官方文档标准地址)
        host = "openspeech.bytedance.com"
        api_url = f"https://{host}/api/v1/tts"

        # 鉴权 Header (注意：官方示例只用了 Authorization)
        header = {"Authorization": f"Bearer;{Config.VOLC_ACCESS_TOKEN}"}

        final_voice = specific_voice if specific_voice else Config.VOLC_DEFAULT_VOICE

        # 3. 构造请求体 (完全照搬官方示例结构)
        request_json = {
            "app": {
                "appid": Config.VOLC_APPID,
                "token": "access_token",  # 官方要求固定填这个字符串
                "cluster": Config.VOLC_CLUSTER_ID  # 确保是 'volcano_tts'
            },
            "user": {
                "uid": "user_001"
            },
            "audio": {
                "voice_type": final_voice,
                "encoding": "mp3",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",  # query 表示同步返回音频
                "with_frontend": 1,
                "frontend_type": "unitTson"
            }
        }

        # 4. 发送请求
        resp = requests.post(api_url, json=request_json, headers=header, timeout=(5, 30))

        # 5. 处理响应
        resp_data = resp.json()

        if "data" in resp_data:
            data = resp_data["data"]
            # 解码并写入文件
            with open(file_path, "wb") as file_to_save:
                file_to_save.write(base64.b64decode(data))

            print(f"✅ 语音生成成功! 耗时: {time.time() - start_time:.2f}s")
            return filename
        else:
            # 打印错误信息
            print(f"❌ 火山引擎报错: {resp_data}")
            # 如果报错 3001，一定是服务没开通或 Cluster ID 填错了
            return None

    except Exception as e:
        print(f"❌ TTS 系统异常: {e}")
        return None


def _text_to_speech_realtime(text, output_dir, specific_voice=None):
    """Read the exact reply via the activated dialogue model, without mic input."""
    if not text or len(text) > 16000:
        return None
    config = {name: getattr(Config, name) for name in (
        'VOLC_API_KEY', 'VOLC_REALTIME_URL', 'VOLC_REALTIME_MODEL',
        'VOLC_REALTIME_RESOURCE_ID', 'VOLC_REALTIME_VOICE', 'VOLC_AVAILABLE_VOICES',
    )}
    voice = resolve_realtime_voice(specific_voice or Config.VOLC_DEFAULT_VOICE, config)
    upstream = None
    pcm = bytearray()
    filename = f'tts_{uuid.uuid4().hex}.wav'
    path = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)
    try:
        upstream = connect_provider(config)
        upstream.send(json.dumps({'type': 'session.create', 'session': {
            'model': config['VOLC_REALTIME_MODEL'],
            'instructions': '你是面试官语音播报员。仅朗读指定文字，不添加或改写内容。',
            'audio': {
                'input': {'format': {'type': 'pcm', 'rate': 16000}},
                'output': {'format': {'type': 'pcm_s16le', 'rate': 24000}, 'voice': voice},
            },
        }}, ensure_ascii=False))
        upstream.settimeout(2)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                raw = upstream.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw or len(raw) > 2 * 1024 * 1024:
                raise ValueError('Invalid speech event')
            event = json.loads(raw)
            kind = event.get('type')
            if kind == 'session.created':
                upstream.send(json.dumps({'type': 'input_audio_mute.commit'}))
                upstream.send(json.dumps({'type': 'speech_text_buffer.commit', 'text': text}, ensure_ascii=False))
            elif kind == 'response.output_audio.delta':
                pcm.extend(base64.b64decode(event['delta'], validate=True))
                if len(pcm) > MAX_AUDIO_BYTES:
                    raise ValueError('Speech output exceeds limit')
            elif kind == 'response.output_audio.done':
                if not pcm or len(pcm) % 2:
                    raise ValueError('Incomplete PCM16 speech')
                with wave.open(path, 'wb') as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(pcm)
                return filename
            elif kind in {'error', 'session.closed'}:
                raise ValueError('Speech provider stopped')
    except Exception as error:
        logging.getLogger(__name__).warning('Realtime text speech failed: %s', type(error).__name__)
    finally:
        if upstream:
            try:
                upstream.send(json.dumps({'type': 'session.close'}))
                # Release the provider session before another reply starts.
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    event = json.loads(upstream.recv())
                    if event.get('type') == 'session.closed':
                        break
            except Exception:
                pass
            try:
                upstream.close()
            except Exception:
                pass
    if os.path.exists(path):
        os.remove(path)
    return None


def _text_to_speech_v3(text, output_dir, specific_voice=None):
    """New API-Key authentication for text-mode and practice speech playback."""
    voice = specific_voice or Config.VOLC_DEFAULT_VOICE
    resource = Config.VOLC_TTS_RESOURCE_ID or (
        'seed-tts-2.0' if '_uranus_' in voice else 'seed-tts-1.0'
    )
    filename = f'tts_{uuid.uuid4().hex}.mp3'
    path = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)
    try:
        with requests.post(
            'https://openspeech.bytedance.com/api/v3/tts/unidirectional',
            headers={'X-Api-Key': Config.VOLC_API_KEY, 'X-Api-Resource-Id': resource,
                     'X-Api-Request-Id': str(uuid.uuid4())},
            json={'user': {'uid': 'interview'}, 'req_params': {
                'text': text, 'speaker': voice,
                'audio_params': {'format': 'mp3', 'sample_rate': 24000},
            }}, stream=True, timeout=(5, 30),
        ) as response:
            response.raise_for_status()
            received = 0
            with open(path, 'wb') as output:
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    code = event.get('code')
                    if code == 20000000:
                        break
                    if code != 0:
                        logging.getLogger(__name__).warning('TTS v3 rejected code=%s', code)
                        raise ValueError('TTS provider rejected request')
                    if event.get('data'):
                        chunk = base64.b64decode(event['data'], validate=True)
                        received += len(chunk)
                        if received > 16 * 1024 * 1024:
                            raise ValueError('TTS output exceeds limit')
                        output.write(chunk)
            if received:
                return filename
    except Exception as error:
        logging.getLogger(__name__).warning('TTS v3 failed: %s', type(error).__name__)
    if os.path.exists(path):
        os.remove(path)
    return None


def split_text_for_tts(text, min_len=18, max_len=70):
    """按句末标点/换行切分，过短则合并，过长则硬切。返回片段列表。"""
    if not text:
        return []
    # 按句号/问号/叹号/换行后的位置切分
    parts = re.split(r'(?<=[。！？!?…\n])', text)
    chunks = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        buf += p
        if len(buf) >= min_len:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)

    # 过长硬切
    final = []
    for c in chunks:
        while len(c) > max_len:
            final.append(c[:max_len])
            c = c[max_len:]
        if c:
            final.append(c)
    return final or [text]


def text_to_speech_chunks(text, output_dir, specific_voice=None):
    """
    分句流式 TTS：逐片生成并 yield (index, filename)。
    失败的片段跳过（不影响整体）。用于 SSE 边生成边播放。
    """
    # The dialogue service accepts a whole forced-speech utterance. Avoid
    # opening a fresh provider session for every sentence of the same reply.
    if Config.VOLC_API_KEY and not Config.VOLC_TTS_RESOURCE_ID:
        fn = text_to_speech(text, output_dir, specific_voice)
        if fn:
            yield 0, fn
        return
    chunks = split_text_for_tts(text)
    for i, chunk in enumerate(chunks):
        fn = text_to_speech(chunk, output_dir, specific_voice)
        if fn:
            yield i, fn

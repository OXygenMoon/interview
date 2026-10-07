"""Normalize camera observations for live feedback and historical reports."""

import base64
import binascii
import json
import re


MAX_FRAME_BYTES = 512 * 1024
UNAVAILABLE_COMMENT = '本次画面分析未完成，无法给出仪态点评。可结合截图自行回顾。'


def decode_frame(value):
    """Accept bounded inline JPEG/PNG snapshots, never arbitrary remote URLs."""
    if not isinstance(value, str) or len(value) > MAX_FRAME_BYTES * 4 // 3 + 100:
        raise ValueError('画面需为不超过 512 KB 的 JPEG 或 PNG 图片')
    match = re.fullmatch(r'data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ValueError('画面需为 JPEG 或 PNG 图片')
    try:
        decoded = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('画面编码无效') from error
    signature = b'\xff\xd8\xff' if match[1] == 'jpeg' else b'\x89PNG\r\n\x1a\n'
    if not decoded.startswith(signature) or len(decoded) > MAX_FRAME_BYTES:
        raise ValueError('画面格式无效或超过 512 KB')
    return decoded


def normalize_visual_feedback(value):
    """Read structured reviews and the historical array/plain-text tag formats."""
    if isinstance(value, str):
        cleaned = value.replace('```json', '').replace('```', '').strip()
        try:
            value = json.loads(cleaned)
        except (ValueError, TypeError):
            value = [tag.strip() for tag in re.split(r'[,，\n]', cleaned) if tag.strip()]
    if isinstance(value, dict):
        tags = value.get('tags', [])
        comment = value.get('comment', '')
    else:
        tags = value if isinstance(value, list) else []
        comment = ''
    tags = [tag.strip()[:80] for tag in tags if isinstance(tag, str) and tag.strip()][:6] if isinstance(tags, list) else []
    comment = comment.strip()[:500] if isinstance(comment, str) else ''
    return {'tags': tags, 'comment': comment}


def visual_record(message, session):
    """Associate the observation with its answer and elapsed capture time."""
    if message.sender != 'user':
        return None
    feedback = normalize_visual_feedback(message.visual_context)
    captured_at = message.visual_captured_at
    has_image = captured_at is not None
    if not (feedback['tags'] or feedback['comment'] or has_image):
        return None
    when = captured_at or message.timestamp
    seconds = max(0, int((when - session.start_time).total_seconds())) if when and session.start_time else 0
    minutes, remainder = divmod(seconds, 60)
    return {
        **feedback,
        'comment': feedback['comment'] or (
            '历史记录仅保存画面关键词，未生成仪态点评。' if feedback['tags'] else UNAVAILABLE_COMMENT
        ),
        'message_id': message.id,
        'has_image': has_image,
        'elapsed': f'{minutes:02d}:{remainder:02d}',
        'clock_time': when.strftime('%H:%M:%S') if when else '',
        'estimated_time': not has_image,
    }

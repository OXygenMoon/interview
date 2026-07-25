"""Retention policy for generated audio and temporary upload files."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import inspect, or_

from .. import db
from ..models import ChatMessage, SystemConfig


def _config_int(key, default):
    try:
        return max(0, int(SystemConfig.get(key, str(default))))
    except (TypeError, ValueError):
        return default


def _audio_filename(url):
    if not url:
        return None
    return Path(urlparse(str(url)).path).name or None


def cleanup_runtime_files(app):
    """Expire old TTS references and remove old generated/temp files."""
    now = datetime.now()
    audio_cutoff = now - timedelta(days=_config_int('audio_retention_days', 30))
    temp_cutoff = now - timedelta(hours=_config_int('temp_retention_hours', 24))
    audio_root = Path(app.root_path) / 'static' / 'uploads' / 'audio'
    temp_roots = [
        Path(app.root_path) / 'static' / 'uploads' / 'temp',
        Path(app.instance_path) / 'uploads' / 'temp',
    ]

    changed_links = 0
    expired_messages = []
    expired_names = set()
    schema_columns = {
        column['name']
        for column in inspect(db.engine).get_columns('chat_messages')
    }
    mapped_columns = {column.name for column in ChatMessage.__table__.columns}
    if mapped_columns <= schema_columns:
        # Remove broken database links left by manual cleanup or old deploys.
        linked_messages = ChatMessage.query.filter(
            or_(
                ChatMessage.audio_url.isnot(None),
                ChatMessage.audio_urls.isnot(None),
            )
        ).all()
        for message in linked_messages:
            urls = message.audio_urls or []
            if isinstance(urls, str):
                try:
                    urls = json.loads(urls)
                except (TypeError, json.JSONDecodeError):
                    urls = []
            candidates = list(urls) if isinstance(urls, list) else []
            if message.audio_url and message.audio_url not in candidates:
                candidates.insert(0, message.audio_url)
            retained = [
                url for url in candidates
                if _audio_filename(url)
                and (audio_root / _audio_filename(url)).is_file()
            ]
            next_url = retained[0] if retained else None
            next_urls = retained or None
            if message.audio_url != next_url or message.audio_urls != next_urls:
                message.audio_url = next_url
                message.audio_urls = next_urls
                changed_links += 1

        expired_messages = ChatMessage.query.filter(
            ChatMessage.timestamp < audio_cutoff,
        ).filter(
            or_(
                ChatMessage.audio_url.isnot(None),
                ChatMessage.audio_urls.isnot(None),
            )
        ).all()
        for message in expired_messages:
            expired_names.add(_audio_filename(message.audio_url))
            urls = message.audio_urls or []
            if isinstance(urls, str):
                try:
                    urls = json.loads(urls)
                except (TypeError, json.JSONDecodeError):
                    urls = []
            for url in urls if isinstance(urls, list) else []:
                expired_names.add(_audio_filename(url))
            message.audio_url = None
            message.audio_urls = None
        if expired_messages or changed_links:
            db.session.commit()

    removed_audio = 0
    audio_root.mkdir(parents=True, exist_ok=True)
    for path in audio_root.iterdir():
        if not path.is_file() or path.name == '.gitkeep':
            continue
        if (
            path.name in expired_names
            or datetime.fromtimestamp(path.stat().st_mtime) < audio_cutoff
        ):
            path.unlink(missing_ok=True)
            removed_audio += 1

    removed_temp = 0
    for root in temp_roots:
        root.mkdir(parents=True, exist_ok=True)
        for path in root.iterdir():
            if not path.is_file() or path.name == '.gitkeep':
                continue
            if datetime.fromtimestamp(path.stat().st_mtime) < temp_cutoff:
                path.unlink(missing_ok=True)
                removed_temp += 1
    return {
        'expired_audio_references': len(expired_messages),
        'cleared_broken_audio_links': changed_links,
        'removed_audio_files': removed_audio,
        'removed_temp_files': removed_temp,
    }

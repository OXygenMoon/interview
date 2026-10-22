"""Private lesson uploads and strictly normalized Bilibili embeds."""
import re
import secrets
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge


VIDEO_ENDPOINTS = {'routes.add_learning_material', 'routes.update_learning_material'}


def init_learning_media(app):
    @app.before_request
    def limit_learning_upload():
        # Flask 3.1 supports a per-request limit; other APIs retain their 8 MB cap.
        if request.endpoint in VIDEO_ENDPOINTS and request.mimetype == 'multipart/form-data':
            request.max_content_length = app.config['LEARNING_VIDEO_MAX_BYTES'] + 1024 * 1024

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(error):
        if request.endpoint in VIDEO_ENDPOINTS:
            limit = app.config['LEARNING_VIDEO_MAX_BYTES'] // (1024 * 1024)
            return jsonify(error=f'视频文件过大，最大支持 {limit} MB'), 413
        return error


class _IframeSource(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'iframe':
            self.sources.append(dict(attrs).get('src', ''))


def normalize_bilibili_url(value):
    """Extract only the source URL; never save or execute pasted iframe HTML."""
    value = value.strip()
    if '<' in value:
        parser = _IframeSource()
        parser.feed(value)
        if len(parser.sources) != 1:
            raise ValueError('请粘贴一个 B 站 iframe 嵌入代码或视频链接')
        value = parser.sources[0]
    if value.startswith('//'):
        value = 'https:' + value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'https', 'http'} or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443}):
            raise ValueError
    except ValueError:
        raise ValueError('请输入有效的 B 站视频链接') from None
    query = parse_qs(parsed.query)
    params = {}
    if parsed.hostname == 'player.bilibili.com' and parsed.path == '/player.html':
        bvid = query.get('bvid', [''])[0]
        aid = query.get('aid', [''])[0]
    elif parsed.hostname in {'www.bilibili.com', 'bilibili.com'}:
        match = re.fullmatch(r'/video/(BV[0-9A-Za-z]{10}|av[0-9]+)/?', parsed.path)
        if not match:
            raise ValueError('请输入 B 站视频页面链接或 iframe 嵌入链接')
        ident = match.group(1)
        bvid, aid = (ident, '') if ident.startswith('BV') else ('', ident[2:])
    else:
        raise ValueError('仅支持 B 站官方视频页面或 player.bilibili.com 的 iframe 链接')
    if re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
        params['bvid'] = bvid
    elif re.fullmatch(r'[1-9][0-9]{0,19}', aid):
        params['aid'] = aid
    else:
        raise ValueError('B 站链接缺少有效的 BV 号或 av 号')
    for key in ('cid', 'p'):
        number = query.get(key, [''])[0]
        if number:
            if not re.fullmatch(r'[1-9][0-9]{0,19}', number):
                raise ValueError('B 站视频分集参数无效')
            params[key] = number
    params['autoplay'] = '0'
    return 'https://player.bilibili.com/player.html?' + urlencode(params)


def video_directory():
    configured = current_app.config.get('LEARNING_VIDEO_UPLOAD_DIR')
    return Path(configured) if configured else Path(current_app.instance_path) / 'uploads' / 'learning'


def valid_video_filename(filename):
    return bool(re.fullmatch(r'[a-f0-9]{32}\.(mp4|m4v|webm)', filename or ''))


def delete_uploaded_video(filename):
    if valid_video_filename(filename):
        try:
            (video_directory() / filename).unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception('Could not remove learning video %s', filename)


def save_uploaded_video(upload):
    extension = Path(upload.filename or '').suffix.lower()
    header = upload.stream.read(32)
    upload.stream.seek(0)
    supported = ((extension in {'.mp4', '.m4v'} and header[4:8] == b'ftyp')
                 or (extension == '.webm' and header.startswith(b'\x1aE\xdf\xa3')))
    if not supported:
        raise ValueError('请上传有效的 MP4、M4V 或 WebM 视频')
    directory = video_directory()
    directory.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(16) + extension
    path = directory / filename
    try:
        size = 0
        with path.open('xb') as target:
            while chunk := upload.stream.read(1024 * 1024):
                size += len(chunk)
                if size > current_app.config['LEARNING_VIDEO_MAX_BYTES']:
                    raise RequestEntityTooLarge()
                target.write(chunk)
        return filename
    except Exception:
        path.unlink(missing_ok=True)
        raise

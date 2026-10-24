"""Bounded public-page collectors, source validation and idempotent aggregation.

No browser cookies, private endpoints, captcha solvers or login automation.
All saved content is plain text. Source failure never deletes cached jobs.
"""
import hashlib
import json
import re
import secrets
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import click
import requests
from flask import current_app
from lxml import html
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import RecruitmentJob, RecruitmentSync

SOURCES = {
    'boss': {'name': 'BOSS直聘', 'hosts': ('www.zhipin.com', 'm.zhipin.com'),
             'pages': ('https://www.zhipin.com/web/geek/job?city=101210300',)},
    'lagou': {'name': '拉勾网', 'hosts': ('www.lagou.com', 'm.lagou.com'),
              'pages': ('https://www.lagou.com/wn/jobs?city=嘉兴',)},
    'jiaxing': {'name': '嘉兴人才网', 'hosts': ('www.573job.com', 'jiashan.573job.com'),
                'pages': ('https://jiashan.573job.com/', 'https://www.573job.com/')},
}
DISTRICTS = ('嘉善', '南湖区', '秀洲区', '平湖', '海盐', '海宁', '桐乡', '嘉兴')
USER_AGENT = 'InterviewJobsBot/1.0'


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def plain(value, limit=20000):
    if not isinstance(value, (str, int, float)):
        return ''
    value = str(value)
    if '<' in value:
        try:
            tree = html.fragment_fromstring(value, create_parent='div')
            for node in tree.xpath('.//script|.//style'):
                node.drop_tree()
            for node in tree.xpath('.//br'):
                node.tail = '\n' + (node.tail or '')
            value = tree.text_content()
        except (ValueError, TypeError):
            value = ''
    return re.sub(r'[ \t\r\f\v]+', ' ', value).strip()[:limit]


def canonical_url(source, url):
    parts = urlsplit(str(url))
    if source not in SOURCES:
        raise ValueError('未知招聘来源')
    invalid = (parts.scheme != 'https', parts.hostname not in SOURCES[source]['hosts'],
               parts.username, parts.password, parts.port not in (None, 443))
    if any(invalid):
        raise ValueError('岗位链接必须是对应招聘网站的 HTTPS 原始岗位链接')
    path = parts.path.lower()
    is_job = {
        'boss': bool(re.fullmatch(r'/job_detail/[^/]+\.html', path)),
        'lagou': bool(re.fullmatch(r'/(?:wn/)?jobs/\d+\.html', path)),
        'jiaxing': path == '/q/stationinfo.aspx' and any(
            key.lower() == 'stationid' and value for key, value in parse_qsl(parts.query)),
    }[source]
    if not is_job:
        raise ValueError('链接应指向具体岗位，而不是平台首页或搜索页')
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query)
                             if k.lower() in ('stationid',)))
    return urlunsplit(('https', parts.hostname, parts.path, query, ''))


def district_for(location):
    for district in DISTRICTS:
        if district in location:
            return district
    return None


def normalize_job(source, item):
    if not isinstance(item, dict):
        raise ValueError('岗位必须是对象')
    title, company = plain(item.get('title'), 200), plain(item.get('company'), 300)
    location = plain(item.get('district') or item.get('location'), 500)
    district = district_for(location)
    if not title or not company or not district:
        raise ValueError('岗位须有名称、企业及明确的嘉兴本地工作地区')
    url = canonical_url(source, item.get('url', ''))
    identity = '|'.join(re.sub(r'\s+', '', unicodedata.normalize('NFKC', v)).casefold()
                        for v in (title, company, district))
    expires = None
    if not isinstance(item.get('is_active', True), bool):
        raise ValueError('is_active 必须为 JSON 布尔值 true 或 false')
    if item.get('expires_at'):
        try:
            expiry_text = str(item['expires_at'])
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', expiry_text):
                expiry_text += 'T23:59:59+08:00'
            expires = datetime.fromisoformat(expiry_text.replace('Z', '+00:00'))
            if expires.tzinfo:
                expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError as exc:
            raise ValueError('岗位截止日期须为 ISO 8601 日期') from exc
    return dict(source=source, source_url=url, group_key=hashlib.sha256(identity.encode()).hexdigest(),
                title=title, company=company, district=district,
                address=plain(item.get('address'), 500), salary=plain(item.get('salary'), 100) or '薪资面议',
                experience=plain(item.get('experience'), 100) or '未注明',
                education=plain(item.get('education'), 100) or '未注明',
                description=plain(item.get('description')),
                published_at=plain(item.get('published_at'), 100), expires_at=expires,
                is_active=item.get('is_active', True) is not False)


def save_jobs(source, items):
    # Validate the whole batch before any writes (imports are atomic).
    values = [normalize_job(source, item) for item in items]
    seen = set()
    for value in values:
        if value['source_url'] in seen:
            continue
        seen.add(value['source_url'])
        row = RecruitmentJob.query.filter_by(source=source, source_url=value['source_url']).first()
        if row is None:
            row = RecruitmentJob(**value, last_seen_at=utcnow())
            db.session.add(row)
        else:
            for key, field in value.items():
                # A list-only response must not erase previously collected details.
                if key in ('description', 'address') and not field:
                    continue
                setattr(row, key, field)
            row.last_seen_at = utcnow()
    return len(seen)


class PublicClient:
    def __init__(self, source):
        self.source = source
        self.robots = {}

    def _get(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in SOURCES[self.source]['hosts']:
            raise ValueError('采集地址不在来源白名单中')
        # Redirects can lead to login/challenge pages or another host: do not follow.
        with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(4, 10),
                          allow_redirects=False, stream=True) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('来源要求跳转或验证，请到原网站查看')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ValueError('来源页面超过采集大小限制')
                chunks.append(chunk)
            body = b''.join(chunks)
            encoding = response.encoding
            if not encoding or encoding.lower() == 'iso-8859-1':
                encoding = 'utf-8'
            return body.decode(encoding, errors='replace')

    def get(self, url):
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self.robots:
            parser = RobotFileParser()
            # Fail closed if robots cannot be obtained; a 404 means no policy.
            try:
                content = self._get(origin + '/robots.txt')
            except requests.HTTPError as exc:
                if exc.response.status_code != 404:
                    raise
                content = 'User-agent: *\nAllow: /'
            parser.parse(content.replace('\\r\\n', '\n').splitlines())
            self.robots[origin] = parser
        if not self.robots[origin].can_fetch(USER_AGENT, url):
            raise ValueError('来源站点的 robots 规则不允许采集此页面')
        time.sleep(current_app.config.get('RECRUITMENT_REQUEST_DELAY', 0.25))
        return self._get(url)


def parse_local_list(body, base_url):
    tree = html.fromstring(body)
    result = []
    for anchor in tree.xpath('//a[contains(@class,"job") and contains(@href,"StationInfo.aspx")]'):
        parent = anchor.getparent()
        companies = parent.xpath('.//a[contains(@class,"firm")]/@title')
        fields = [plain(v) for v in anchor.xpath('./p/span/text()')]
        salaries = anchor.xpath('./p/b/text()')
        if not companies or not fields:
            continue
        result.append(dict(title=anchor.get('title') or plain(anchor.text_content(), 200),
                           company=companies[0], url=urljoin(base_url, anchor.get('href')),
                           district=fields[0], salary=salaries[-1] if len(salaries) > 1 else '',
                           experience=fields[1] if len(fields) > 1 else '',
                           education=fields[2] if len(fields) > 2 else ''))
    return result


def parse_local_detail(body):
    tree = html.fromstring(body)

    def section(title):
        nodes = tree.xpath('//h3[text()=$title]/../following-sibling::div[1]', title=title)
        if not nodes:
            return ''
        for node in nodes[0].xpath('.//br'):
            node.tail = '\n' + (node.tail or '')
        return plain(nodes[0].text_content())
    addresses = tree.xpath('//*[@id="txt_address"]/text()')
    return {'description': section('职位描述'),
            'address': plain(addresses[0], 500) if addresses else ''}


def parse_structured_jobs(body, base_url):
    """Read public Schema.org JobPosting; never execute embedded JavaScript."""
    tree = html.fromstring(body)
    result = []

    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
                organization = node.get('hiringOrganization') or {}
                locations = node.get('jobLocation') or []
                if isinstance(locations, dict):
                    locations = [locations]
                salary = node.get('baseSalary') or {}
                value = salary.get('value') if isinstance(salary, dict) else None
                salary_text = ''
                if isinstance(value, dict):
                    amounts = [str(value[k]) for k in ('minValue', 'maxValue') if value.get(k) is not None]
                    if not amounts and value.get('value') is not None:
                        amounts = [str(value['value'])]
                    salary_text = '-'.join(amounts)
                    if salary_text:
                        salary_text += f" {salary.get('currency', 'CNY')}/{value.get('unitText', '未注明周期')}"
                for place in locations:
                    address = place.get('address') or {}
                    address_text = ' '.join(plain(address.get(key)) for key in
                                            ('addressRegion', 'addressLocality', 'streetAddress'))
                    result.append(dict(title=node.get('title'), company=organization.get('name'),
                        url=urljoin(base_url, node.get('url') or ''), location=address_text,
                        address=address_text, description=node.get('description'), salary=salary_text,
                        education=plain(node.get('educationRequirements')),
                        experience=plain(node.get('experienceRequirements')),
                        published_at=node.get('datePosted'), expires_at=node.get('validThrough')))
            for key, child in node.items():
                if isinstance(child, (list, dict)) and key != 'jobLocation':
                    walk(child)
    for script in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            walk(json.loads(script))
        except (ValueError, TypeError, AttributeError):
            continue
    return result


def collect_source(source, limit):
    client = PublicClient(source)
    rows, seen, warnings = [], set(), []
    for page in SOURCES[source]['pages']:
        try:
            body = client.get(page)
        except (requests.RequestException, ValueError) as exc:
            warnings.append(type(exc).__name__)
            continue
        candidates = parse_local_list(body, page) if source == 'jiaxing' else parse_structured_jobs(body, page)
        for item in candidates:
            try:
                normalized = normalize_job(source, item)
            except ValueError:
                continue
            if normalized['source_url'] in seen:
                continue
            seen.add(normalized['source_url'])
            if source == 'jiaxing':
                try:
                    item.update(parse_local_detail(client.get(normalized['source_url'])))
                except (requests.RequestException, ValueError):
                    warnings.append('detail')
            rows.append(item)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError('未能读取公开岗位，可能需要登录、验证或页面已变更；请到原网站查看，或导入授权数据。')
    return rows, bool(warnings)


def sync_source(source, items=None, limit=30):
    if source not in SOURCES:
        raise ValueError('未知招聘来源')
    now, token = utcnow(), secrets.token_hex(16)
    state = db.session.get(RecruitmentSync, source)
    if state is None:
        db.session.add(RecruitmentSync(source=source))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
    acquired = RecruitmentSync.query.filter_by(source=source).filter(or_(
        RecruitmentSync.lease_token.is_(None), RecruitmentSync.started_at < now - timedelta(minutes=10)
    )).update(dict(lease_token=token, started_at=now, status='running', message='正在采集公开岗位'))
    db.session.commit()
    if not acquired:
        return {'source': source, 'status': 'running', 'count': 0, 'message': '此来源正在更新，请稍后查看'}
    try:
        warnings = False
        if items is None:
            items, warnings = collect_source(source, limit)
        count = save_jobs(source, items)
        state = db.session.get(RecruitmentSync, source)
        # Only the current lease owner may commit its results.
        if state.lease_token != token:
            raise ValueError('采集任务已超时，请重试')
        state.status = 'partial' if warnings else 'success'
        state.message = f'已更新 {count} 条来源记录' + ('；部分页面未能读取，保留已有信息' if warnings else '')
        state.job_count = count
        state.succeeded_at = utcnow()
        state.finished_at = utcnow()
        state.lease_token = None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('Recruitment sync failed (%s): %s', source, type(exc).__name__)
        state = db.session.get(RecruitmentSync, source)
        if state.lease_token == token:
            state.status = 'failed'
            state.message = str(exc)[:450] if isinstance(exc, ValueError) else '来源暂时无法访问，请稍后重试；已保存的岗位仍可查询'
            state.finished_at = utcnow()
            state.lease_token = None
            db.session.commit()
    return {'source': source, 'status': state.status, 'count': state.job_count, 'message': state.message}


def register_recruitment_commands(app):
    @app.cli.command('sync-jobs')
    @click.option('--source', type=click.Choice(tuple(SOURCES)))
    @click.option('--limit', type=click.IntRange(1, 100), default=30, show_default=True)
    @click.option('--file', 'input_file', type=click.File('r', encoding='utf-8'), help='导入授权的岗位 JSON 数组；须指定来源')
    def sync_jobs_command(source, limit, input_file):
        """Collect Jiashan/Jiaxing public jobs; suitable for an external timer."""
        items = None
        if input_file:
            if not source:
                raise click.UsageError('--file 必须与 --source 一起使用')
            try:
                items = json.load(input_file)
                if not isinstance(items, list) or not items or len(items) > 5000:
                    raise ValueError('文件应为非空 JSON 数组，最多 5000 条')
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        failures = []
        for key in ([source] if source else SOURCES):
            result = sync_source(key, items=items, limit=limit)
            click.echo(f"{key}: {result['status']} — {result['message']}")
            if result['status'] in ('failed', 'running'):
                failures.append(key)
        if failures:
            raise click.ClickException('以下来源未完成更新：' + ', '.join(failures))

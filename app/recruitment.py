"""Authenticated local vacancy search, grouped details and admin source refresh."""
from collections import OrderedDict
from datetime import timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func, or_

from .decorators import admin_required
from .models import RecruitmentJob, RecruitmentSync
from .services.recruitment import DISTRICTS, SOURCES, sync_source, utcnow

bp = Blueprint('recruitment', __name__, url_prefix='/jobs')


def available(query, now=None):
    now = now or utcnow()
    return query.filter(RecruitmentJob.is_active.is_(True),
        or_(RecruitmentJob.expires_at.is_(None), RecruitmentJob.expires_at >= now),
        RecruitmentJob.last_seen_at >= now - timedelta(days=30))


def group_rows(rows):
    now = utcnow()

    def is_current(row):
        return all((row.is_active, not row.expires_at or row.expires_at >= now,
                    row.last_seen_at >= now - timedelta(days=30)))

    groups = OrderedDict()
    for row in rows:
        groups.setdefault(row.group_key, []).append(row)
    for values in groups.values():
        values.sort(key=lambda row: not is_current(row))
    return [{'key': key, 'job': values[0], 'origins': values,
             'sources': list(dict.fromkeys(row.source for row in values)),
             'stale': not is_current(values[0]) or values[0].last_seen_at < now - timedelta(days=7)}
            for key, values in groups.items()]


@bp.app_template_filter('job_time')
def job_time(value):
    if not value:
        return '尚未更新'
    from datetime import timezone
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')


@bp.get('')
@login_required
def index():
    now = utcnow()
    keyword = request.args.get('q', '').strip()[:100]
    district = request.args.get('district', '')
    source = request.args.get('source', '')
    sort = request.args.get('sort', 'recent')
    if district not in DISTRICTS:
        district = ''
    if source not in SOURCES:
        source = ''
    if sort not in ('recent', 'title', 'company'):
        sort = 'recent'
    include_old = request.args.get('include_old') == '1'
    query = RecruitmentJob.query
    if not include_old:
        query = available(query, now)
    if keyword:
        pattern = '%' + keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(*(column.ilike(pattern, escape='\\') for column in
            (RecruitmentJob.title, RecruitmentJob.company, RecruitmentJob.description))))
    if district:
        query = query.filter(RecruitmentJob.district == district)
    if source:
        query = query.filter(RecruitmentJob.source == source)
    groups = query.with_entities(RecruitmentJob.group_key,
        func.max(RecruitmentJob.last_seen_at).label('last_seen'))
    groups = groups.group_by(RecruitmentJob.group_key)
    order = {'recent': func.max(RecruitmentJob.last_seen_at).desc(),
             'title': func.min(RecruitmentJob.title).asc(),
             'company': func.min(RecruitmentJob.company).asc()}[sort]
    groups = groups.order_by(order, RecruitmentJob.group_key)
    pagination = groups.paginate(page=max(request.args.get('page', 1, type=int) or 1, 1), per_page=15, error_out=False)
    keys = [row.group_key for row in pagination.items]
    # Show all current platform versions of a matched group, even when one source matched a search.
    origins = RecruitmentJob.query.filter(RecruitmentJob.group_key.in_(keys))
    if not include_old:
        origins = available(origins, now)
    grouped = {group['key']: group for group in group_rows(origins.order_by(RecruitmentJob.last_seen_at.desc(), RecruitmentJob.id.desc()).all())}
    states = {state.source: state for state in RecruitmentSync.query.all()}
    total = available(RecruitmentJob.query, now).with_entities(RecruitmentJob.group_key).distinct().count()
    local_total = available(RecruitmentJob.query, now).filter_by(district='嘉善').with_entities(RecruitmentJob.group_key).distinct().count()
    filters = dict(q=keyword, district=district, source=source, sort=sort, include_old='1' if include_old else '')
    return render_template('jobs_index.html', jobs=[grouped[key] for key in keys],
        pagination=pagination, filters=filters, sources=SOURCES, districts=DISTRICTS,
        states=states, total=total, local_total=local_total,
        previous_url=url_for('recruitment.index', **filters, page=pagination.prev_num) if pagination.has_prev else None,
        next_url=url_for('recruitment.index', **filters, page=pagination.next_num) if pagination.has_next else None)


@bp.get('/<string:group_key>')
@login_required
def detail(group_key):
    rows = RecruitmentJob.query.filter_by(group_key=group_key).order_by(
        RecruitmentJob.is_active.desc(), RecruitmentJob.last_seen_at.desc(), RecruitmentJob.id.desc()).all()
    if not rows:
        abort(404)
    active_ids = {row.id for row in available(RecruitmentJob.query.filter_by(group_key=group_key)).all()}
    rows.sort(key=lambda row: row.id not in active_ids)
    # Only construct a local return URL from allowlisted search parameters.
    filters = {key: request.args[key] for key in ('q', 'district', 'source', 'sort', 'include_old', 'page') if key in request.args}
    return render_template('job_detail.html', job=rows[0], origins=rows, sources=SOURCES,
                           active_ids=active_ids, back_url=url_for('recruitment.index', **filters))


@bp.post('/sync')
@login_required
@admin_required
def sync():
    source = request.form.get('source')
    if source not in SOURCES:
        abort(400)
    result = sync_source(source, limit=30)
    flash(f"{SOURCES[source]['name']}：{result['message']}",
          'success' if result['status'] == 'success' else 'warning')
    return redirect(url_for('recruitment.index', source=source), code=303)

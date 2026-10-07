"""Company workspace and administrator-managed school partnerships."""
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for, send_file
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from . import db
from .decorators import admin_required
from .models import Company, CompanyAccount, Position, InterviewSession, ChatMessage, User
from .services.company_matching import recommend_students
from .services.visual_review import visual_record

bp = Blueprint('company_portal', __name__)


def company_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.role != 'company' or not current_user.company_account:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def own_position(position_id):
    return Position.query.filter_by(
        id=position_id, company_id=current_user.company_account.company_id,
    ).first_or_404()


def company_sessions():
    return InterviewSession.query.join(Position).join(User, InterviewSession.user_id == User.id).filter(
        Position.company_id == current_user.company_account.company_id,
        User.role == 'student', InterviewSession.deleted_at.is_(None),
        InterviewSession.status.in_(['processing', 'completed', 'failed']),
    )


def required_text(name, limit, label):
    value = request.form.get(name, '').strip()
    if not value or len(value) > limit:
        raise ValueError(f'{label}不能为空，且最多 {limit} 个字符。')
    return value


@bp.before_app_request
def isolate_company_workspace():
    if not current_user.is_authenticated or current_user.role != 'company':
        return
    endpoint = request.endpoint or ''
    if endpoint in {'routes.home', 'routes.dashboard'}:
        return redirect(url_for('company_portal.dashboard'))
    allowed = {
        'static', 'healthz', 'readyz', 'queuez',
        'auth.login', 'auth.logout', 'auth.change_password',
        'company_api.get_company_list', 'company_api.get_position_detail',
        'company_api.create_position', 'company_api.update_position',
    }
    if not endpoint.startswith('company_portal.') and endpoint not in allowed:
        abort(403)


@bp.after_request
def private_company_data(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.route('/admin/partnerships', methods=['GET', 'POST'])
@login_required
@admin_required
def partnerships():
    if request.method == 'POST':
        try:
            username = required_text('username', 50, '账号')
            contact = required_text('truename', 50, '联系人')
            password = request.form.get('password', '')
            if not 10 <= len(password) <= 128:
                raise ValueError('初始密码需要 10–128 个字符。')
            company_id = request.form.get('company_id', type=int)
            if request.form.get('company_id') and company_id is None:
                raise ValueError('请选择有效的公司。')
            if company_id:
                company = db.get_or_404(Company, company_id)
            else:
                company = Company(name=required_text('company_name', 100, '公司名称'),
                                  description=request.form.get('description', '').strip()[:20000])
                db.session.add(company)
            user = User(username=username, truename=contact, role='company', active=True,
                        must_change_password=True)
            user.set_password(password)
            db.session.add(CompanyAccount(user=user, company=company))
            db.session.commit()
            flash('公司账号已开通，首次登录需修改密码。', 'success')
            return redirect(url_for('.partnerships'))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        except IntegrityError:
            db.session.rollback()
            flash('该账号已存在，请使用其他账号。', 'error')
    return render_template('admin_partnerships.html',
                           companies=Company.query.order_by(Company.name).all(),
                           accounts=CompanyAccount.query.order_by(CompanyAccount.created_at.desc()).all())


@bp.post('/admin/partnerships/<int:user_id>')
@login_required
@admin_required
def manage_account(user_id):
    account = db.get_or_404(CompanyAccount, user_id)
    action = request.form.get('action')
    if action == 'toggle':
        account.user.active = not account.user.active
        account.user.deactivated_at = None if account.user.active else datetime.now()
        flash('公司账号已启用。' if account.user.active else '公司账号已停用。', 'success')
    elif action == 'reset':
        password = request.form.get('password', '')
        if not 10 <= len(password) <= 128:
            flash('新临时密码需要 10–128 个字符。', 'error')
            return redirect(url_for('.partnerships'))
        account.user.set_password(password)
        account.user.must_change_password = True
        flash('密码已重置，下次登录需修改密码。', 'success')
    elif action == 'contact':
        try:
            account.user.truename = required_text('truename', 50, '联系人')
        except ValueError as error:
            flash(str(error), 'error')
            return redirect(url_for('.partnerships'))
        flash('联系人已更新。', 'success')
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for('.partnerships'))


@bp.get('/company')
@login_required
@company_required
def dashboard():
    company = current_user.company_account.company
    records = company_sessions()
    return render_template('company_dashboard.html', company=company,
                           interview_count=records.count(),
                           candidate_count=records.with_entities(InterviewSession.user_id).distinct().count(),
                           recent=records.order_by(InterviewSession.start_time.desc()).limit(5).all())


@bp.get('/company/positions')
@login_required
@company_required
def positions():
    return render_template('company_positions.html', company=current_user.company_account.company)


@bp.route('/company/positions/new', methods=['GET', 'POST'])
@bp.route('/company/positions/<int:position_id>/edit', methods=['GET', 'POST'])
@login_required
@company_required
def edit_position(position_id=None):
    position = own_position(position_id) if position_id is not None else None
    if request.method == 'POST':
        try:
            name = required_text('name', 100, '岗位名称')
            description = request.form.get('description', '').strip()
            if len(description) > 20000:
                raise ValueError('岗位要求最多 20000 个字符。')
            if position is None:
                position = Position(company_id=current_user.company_account.company_id)
                db.session.add(position)
            position.name, position.description = name, description
            db.session.commit()
            flash('岗位已保存，学生可在面试大厅选择该岗位。', 'success')
            return redirect(url_for('.positions'))
        except ValueError as error:
            flash(str(error), 'error')
    return render_template('company_position_edit.html', position=position)


@bp.get('/company/interviews')
@login_required
@company_required
def interviews():
    position_id = request.args.get('position_id', type=int)
    selected = own_position(position_id) if position_id is not None else None
    query = company_sessions()
    if selected:
        query = query.filter(InterviewSession.position_id == selected.id)
    page = query.order_by(InterviewSession.start_time.desc(), InterviewSession.id.desc()).paginate(
        page=request.args.get('page', 1, type=int), per_page=20, error_out=False)
    now = datetime.now()
    stats = {'all': query.count()}
    for label, duration in [('1h', timedelta(hours=1)), ('24h', timedelta(hours=24)),
                            ('1week', timedelta(days=7)), ('1month', timedelta(days=30)),
                            ('1year', timedelta(days=365))]:
        stats[label] = query.filter(InterviewSession.start_time >= now - duration).count()
    return render_template('company_interviews.html', company=current_user.company_account.company,
                           selected=selected, pagination=page, sessions=page.items, stats=stats,
                           company_view=True, base_template='company_base.html')


@bp.get('/company/interviews/<int:session_id>')
@login_required
@company_required
def interview_detail(session_id):
    record = company_sessions().filter(InterviewSession.id == session_id).first_or_404()
    messages = ChatMessage.query.filter_by(session_id=record.id).order_by(ChatMessage.timestamp, ChatMessage.id).all()
    return render_template('company_interview_detail.html', session=record, messages=messages,
                           base_template='company_base.html',
                           back_url=url_for('.interviews', position_id=record.position_id),
                           back_label='返回面试记录',
                           conversation_url=url_for('.conversation', session_id=record.id),
                           submitted_resume_url=url_for('.submitted_resume', session_id=record.id),
                           frame_endpoint='company_portal.interview_frame',
                           visual_records={message.id: review for message in messages
                                           if (review := visual_record(message, record))})


@bp.get('/company/interviews/<int:session_id>/resume')
@login_required
@company_required
def submitted_resume(session_id):
    record = company_sessions().filter(InterviewSession.id == session_id).first_or_404()
    # Only the submitted snapshot, never the student's current resume library.
    document = record.resume_document_snapshot or {}
    resume = SimpleNamespace(title=document.get('title') or '递交简历',
                             template_id=document.get('template_id') or 'classic',
                             content=document.get('content') or {})
    return render_template('company_submitted_resume.html', record=record, resume=resume,
                           student=record.user, base_template='company_base.html',
                           submitted_text=record.resume_snapshot if not document else None,
                           no_resume=not (record.resume_snapshot or document),
                           back_url=url_for('.interview_detail', session_id=record.id))


@bp.get('/company/interviews/<int:session_id>/conversation')
@login_required
@company_required
def conversation(session_id):
    record = company_sessions().filter(InterviewSession.id == session_id).first_or_404()
    messages = ChatMessage.query.filter_by(session_id=record.id).order_by(ChatMessage.timestamp, ChatMessage.id).all()
    timer_end = record.end_time or record.last_activity or record.start_time
    return render_template('chat.html', session=record, messages=messages, is_read_only=True,
                           base_template='company_base.html', enable_video=False,
                           enable_realtime_voice=False, enable_tts=False, timer_running=False,
                           elapsed_seconds=max(0, int((timer_end - record.start_time).total_seconds())),
                           report_url=url_for('.interview_detail', session_id=record.id),
                           frame_endpoint='company_portal.interview_frame',
                           visual_records={message.id: review for message in messages
                                           if (review := visual_record(message, record))})


@bp.get('/company/interviews/<int:session_id>/frames/<int:message_id>')
@login_required
@company_required
def interview_frame(session_id, message_id):
    record = company_sessions().filter(InterviewSession.id == session_id).first_or_404()
    message = ChatMessage.query.filter_by(id=message_id, session_id=record.id, sender='user').first_or_404()
    if not message.visual_image:
        abort(404)
    mimetype = 'image/png' if message.visual_image.startswith(b'\x89PNG') else 'image/jpeg'
    response = send_file(BytesIO(message.visual_image), mimetype=mimetype)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/company/positions/<int:position_id>/recommendations')
@login_required
@company_required
def recommendations(position_id):
    position = own_position(position_id)
    candidates = recommend_students(company_sessions().filter(InterviewSession.position_id == position.id))
    return render_template('company_recommendations.html', position=position, candidates=candidates)

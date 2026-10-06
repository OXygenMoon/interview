"""Interview is the only writer for cross-platform links and login tickets."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import AccountLink, AccountLinkTicket, User
from .account_link import LinkError, server_call, user_identity


def digest(value):
    if not isinstance(value, str) or not 30 <= len(value) <= 100:
        raise LinkError('凭证无效或已过期，请重新发起。')
    return hashlib.sha256(value.encode()).hexdigest()


def identity(site, user_id):
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise LinkError('账号标识无效。')
    if site == 'interview':
        return user_identity(db.session.get(User, user_id))
    return server_call('wikibook', '/internal/account-link/user', {'user_id': user_id})


def actor_identity(site, data):
    user_id = data.get('user_id')
    if site == 'interview':
        return identity(site, user_id)
    # The authenticated WikiBook server asserts its own local user. Calling
    # back into it while it waits on us would deadlock a single-worker server.
    asserted = data.get('actor_identity')
    if (not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0
            or not isinstance(asserted, dict) or asserted.get('id') != user_id
            or not isinstance(asserted.get('username'), str)
            or not 1 <= len(asserted['username']) <= 80
            or not isinstance(asserted.get('version'), str)
            or len(asserted['version']) != 64):
        raise LinkError('账号标识无效。')
    return asserted


def link_query(site, user_id):
    column = AccountLink.interview_user_id if site == 'interview' else AccountLink.wikibook_user_id
    return AccountLink.query.filter(column == user_id)


def get_ticket(site, code, purpose, consume=False):
    query = AccountLinkTicket.query.filter(
        AccountLinkTicket.digest == digest(code),
        AccountLinkTicket.purpose == purpose,
        AccountLinkTicket.source_site != site,
        AccountLinkTicket.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
        AccountLinkTicket.consumed.is_(False),
    )
    if consume:
        # UPDATE is the claim: two requests cannot both redeem the same code.
        if query.update({'consumed': True}, synchronize_session=False) != 1:
            db.session.rollback()
            raise LinkError('凭证无效、已使用或已过期，请重新发起。')
        ticket = db.session.get(AccountLinkTicket, digest(code), populate_existing=True)
    else:
        ticket = query.first()
    if not ticket:
        raise LinkError('凭证无效、已使用或已过期，请重新发起。')
    source = identity(ticket.source_site, ticket.source_user_id)
    if source['version'] != ticket.source_version:
        raise LinkError('账号凭证已更新，请重新发起。', 403)
    return ticket


def issue(site, source, purpose, **fields):
    AccountLinkTicket.query.filter(AccountLinkTicket.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)).delete()
    # A new request replaces unfinished requests of the same purpose for this account.
    AccountLinkTicket.query.filter_by(source_site=site, source_user_id=source['id'], purpose=purpose).delete()
    code = secrets.token_urlsafe(32)
    db.session.add(AccountLinkTicket(
        digest=digest(code), purpose=purpose, source_site=site,
        source_user_id=source['id'], source_version=source['version'],
        source_username=source['username'],
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=300 if purpose == 'link' else 60),
        **fields,
    ))
    db.session.commit()
    return {'code': code}


def operate(action, site, data):
    try:
        return _operate(action, site, data)
    except IntegrityError:
        db.session.rollback()
        raise LinkError('其中一个账号已关联其他账号，请先解除原有关联。', 409) from None
    except Exception:
        db.session.rollback()
        raise


def _operate(action, site, data):
    if action == 'learning_achievements':
        if site != 'wikibook':
            raise LinkError('操作无效。')
        source = actor_identity(site, data)
        from ..services.learning_achievements import linked_learning_achievements
        return linked_learning_achievements(source['id'], data)

    if action in {'link_inspect', 'link_confirm'}:
        target = actor_identity(site, data)
        ticket = get_ticket(site, data.get('code'), 'link', consume=action == 'link_confirm')
        if action == 'link_inspect':
            return {'username': ticket.source_username}
        ids = {site: target['id'], ticket.source_site: ticket.source_user_id}
        names = {site: target['username'], ticket.source_site: ticket.source_username}
        existing = AccountLink.query.filter(or_(
            AccountLink.interview_user_id == ids['interview'],
            AccountLink.wikibook_user_id == ids['wikibook'],
        )).first()
        if existing:
            raise LinkError('其中一个账号已关联其他账号，请先解除原有关联。', 409)
        db.session.add(AccountLink(
            id=str(uuid.uuid4()), interview_user_id=ids['interview'],
            wikibook_user_id=ids['wikibook'], interview_username=names['interview'],
            wikibook_username=names['wikibook'],
        ))
        db.session.commit()
        from ..services.learning_achievements import notify_wikibook_learning_change
        notify_wikibook_learning_change(ids['interview'])
        return {'linked': True}

    if action == 'login_redeem':
        ticket = get_ticket(site, data.get('code'), 'login', consume=True)
        if ticket.state_digest != digest(data.get('state')):
            raise LinkError('切换会话不匹配，请重新发起。')
        link = db.session.get(AccountLink, ticket.link_id, with_for_update=True)
        if not link:
            raise LinkError('账号关联已解除，请重新关联。', 409)
        expected_source = link.interview_user_id if ticket.source_site == 'interview' else link.wikibook_user_id
        expected_target = link.interview_user_id if site == 'interview' else link.wikibook_user_id
        if ticket.source_user_id != expected_source or ticket.target_user_id != expected_target:
            raise LinkError('账号关联已改变，请重新发起。', 409)
        if site == 'interview':
            target = identity(site, ticket.target_user_id)
            if target['version'] != ticket.target_version:
                raise LinkError('账号凭证已更新，请重新发起。', 403)
        # WikiBook validates its target locally after redemption; no recursive
        # server call is needed while its callback request waits on Interview.
        db.session.commit()
        return {'user_id': ticket.target_user_id, 'version': ticket.target_version}

    if action not in {'status', 'unlink', 'link_start', 'login_issue'}:
        raise LinkError('操作无效。')
    source = actor_identity(site, data)
    link = link_query(site, source['id']).with_for_update().first()
    if action == 'status':
        return {'linked': bool(link), 'username': (
            link.wikibook_username if site == 'interview' else link.interview_username
        ) if link else None}
    if action == 'unlink':
        if link:
            AccountLinkTicket.query.filter(or_(
                AccountLinkTicket.link_id == link.id,
                (AccountLinkTicket.source_site == 'interview') & (AccountLinkTicket.source_user_id == link.interview_user_id),
                (AccountLinkTicket.source_site == 'wikibook') & (AccountLinkTicket.source_user_id == link.wikibook_user_id),
            )).delete(synchronize_session=False)
            db.session.delete(link)
            db.session.commit()
        return {'linked': False}
    if action == 'link_start':
        if link:
            raise LinkError('账号已经关联，请先解除原有关联。', 409)
        return issue(site, source, 'link')
    if not link:
        raise LinkError('请先关联另一平台账号。', 409)
    peer = 'wikibook' if site == 'interview' else 'interview'
    target_id = link.wikibook_user_id if site == 'interview' else link.interview_user_id
    target = identity(peer, target_id)
    return issue(site, source, 'login', target_user_id=target_id,
                 target_version=target['version'], link_id=link.id,
                 state_digest=digest(data.get('state')))

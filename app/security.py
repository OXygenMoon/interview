"""Small security helpers shared by the server-rendered app and JSON APIs."""

import hmac
import secrets

from flask import abort, current_app, request, session


UNSAFE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def init_csrf_protection(app):
    """Protect every cookie-authenticated state change with a session token."""

    def csrf_token():
        token = session.get('_csrf_token')
        if not token:
            token = secrets.token_urlsafe(32)
            session['_csrf_token'] = token
        return token

    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def verify_csrf_token():
        if request.method not in UNSAFE_METHODS:
            return None
        if current_app.testing or not current_app.config.get('CSRF_ENABLED', True):
            return None

        expected = session.get('_csrf_token')
        supplied = (
            request.headers.get('X-CSRF-Token')
            or request.headers.get('X-CSRFToken')
            or request.form.get('csrf_token')
        )
        if (
            not expected
            or not supplied
            or not hmac.compare_digest(str(expected), str(supplied))
        ):
            abort(400, description='CSRF token missing or invalid')

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault(
            'Permissions-Policy',
            'camera=(self), microphone=(self), geolocation=()',
        )
        return response

"""WSGI application behind a single trusted, local Nginx proxy."""

import production_settings  # noqa: F401 -- configure before create_app
from app import create_app
from werkzeug.middleware.proxy_fix import ProxyFix


app = create_app()
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


"""Production Web entrypoint; validate capacity on the deployment host."""

import os


bind = f"{os.environ.get('APP_HOST', '127.0.0.1')}:{int(os.environ.get('APP_PORT', '5001'))}"
worker_class = 'gthread'
workers = int(os.environ.get('WEB_WORKERS', '4'))
threads = int(os.environ.get('WEB_THREADS', '16'))
worker_connections = 1024

# A gthread worker keeps heartbeating during active SSE/WebSocket sessions.
# These are worker liveness / shutdown limits, not a session duration limit.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Avoid recycling workers and interrupting long-lived interviews by request count.
max_requests = 0
preload_app = False
reload = False
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('WEB_LOG_LEVEL', 'info')
capture_output = True


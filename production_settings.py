"""Database settings shared by production Web and report worker processes."""

import os

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()

from app.config import Config


database_url = make_url(Config.SQLALCHEMY_DATABASE_URI)
if database_url.get_backend_name() == 'sqlite' and database_url.database not in (
    None, '', ':memory:',
):
    # Long-lived responses can hold connections. Match the request thread pool
    # and wait for short concurrent writes instead of failing after five seconds.
    Config.SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'timeout': 20},
        'pool_size': int(os.environ.get('WEB_THREADS', '16')),
        'max_overflow': 0,
        'pool_timeout': 20,
        'pool_pre_ping': True,
    }


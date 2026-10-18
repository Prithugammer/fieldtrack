"""WSGI entry point: `gunicorn -w 1 wsgi:app` (or `waitress-serve wsgi:app`).

Run exactly ONE worker process: safety state, the audit log and the login limiter live in the
memory of the process (see README, "Deployment notes"). The safety heartbeat is started here so
escalation keeps running with no browser open.
"""

from app import create_app
from safety import start_background_services

app = create_app()
start_background_services(app)

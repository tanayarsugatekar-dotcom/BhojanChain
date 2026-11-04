"""WSGI entry point for hosts such as PythonAnywhere."""
from a2wsgi import ASGIMiddleware

from main import app, initialize_app

initialize_app()
application = ASGIMiddleware(app)

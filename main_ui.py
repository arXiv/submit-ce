"""Simple file to run submit ui in debug mode.

Run as `python main.py`"""
import os
from submit_ce.ui.factory import create_web_app

# This can make the development log easier to read, by
# removing log messages for GET /static/*
import logging
logging.getLogger("werkzeug").setLevel(logging.WARNING)

if __name__ == "__main__":
    os.environ['TEMPLATES_AUTO_RELOAD'] = "1"
    app = create_web_app()
    if os.environ.get('PROFILE', False):
        from werkzeug.middleware.profiler import ProfilerMiddleware
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, profile_dir="./profs")
        print("WARNING: Profiling, will be slower. Writing to ./profs ")
    app.run(debug=True, port=8080)

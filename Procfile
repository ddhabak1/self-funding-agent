# Process types for buildpack platforms (Heroku-style, Railway, Render).
# web:    HTTP application-server mode — binds $PORT and answers health checks.
#         Also auto-runs the autonomous loop in a background thread.
# worker: pure 24x7 background worker (no HTTP) for platforms that support it.
web: python -m agent.server
worker: python -m agent.watchdog

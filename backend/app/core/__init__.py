"""App-wide plumbing that every other layer may import. Nothing here knows about a feature.

    settings.py        Settings (env vars prefixed WINNIE_, read from the repo-root .env) and
                       REPO_ROOT, the repository root used to resolve relative data paths.
    logging_config.py  setup_logging() and RequestLogMiddleware (one access-log line per request).
    deadlines.py       Spoken deadline ("by Monday noon") -> datetime in America/New_York, or None.

Keep this package free of imports from routes/, services/ or agents/ so it can never form an
import cycle.
"""

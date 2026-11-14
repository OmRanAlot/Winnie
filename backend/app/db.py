# Database engine + session factory (SQLAlchemy 2.x).
#
# TODO:
#   - Engine from settings.DATABASE_URL. DB not chosen yet: SQLite for local dev, likely Postgres in prod.
#   - `get_session` dependency for FastAPI.
#   - Alembic migrations: run `uv run alembic init migrations` once models exist.

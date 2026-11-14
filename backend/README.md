# Winnie backend

FastAPI service managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create .venv and install deps
cp .env.example .env             # fill in secrets
uv run fastapi dev app/main.py   # dev server (once app/main.py has code)
uv run pytest                    # all tests
uv run pytest tests/unit/test_x.py::test_name   # single test
uv run ruff check .              # lint
```

Layering rules are in `app/__init__.py`.

## Browser recordings

The frontend performs recording and transcription with browser APIs. No transcription provider or API key is used by the backend.

`POST /api/recordings` accepts the self-contained JSON documented in `frontend/README.md`, validates base64 audio and metadata, and saves a uniquely named file under `backend/data/recordings/`. The success envelope returns `data.filename`. Audio is limited to 10 MB and JSON requests to 15 MB. Saved files are gitignored. This is local development storage; the endpoint has no authentication and should not be exposed publicly without access controls.

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

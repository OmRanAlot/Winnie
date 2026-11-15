"""Start the API server. Production behaviour by default; `--local` is for a laptop.

    uv run python -m app.cli.serve --local      # reload on save, listens on 127.0.0.1 only
    uv run python -m app.cli.serve              # same as production: all interfaces, no reload

`--local` sets WINNIE_MODE=local for this one process only (a real environment variable beats
every .env file). Nothing is written to disk, so it cannot leak into a deployment: Cloud Run
starts uvicorn itself and never sees this flag, and WINNIE_MODE stays "prod" there.
Supabase, Gemini and every other service keep using whatever your .env points at.
"""

import argparse
import os
from collections.abc import Sequence

import uvicorn

DEFAULT_PORT = 8000


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Winnie API.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run on this laptop: WINNIE_MODE=local, auto-reload, bind 127.0.0.1.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.local:
        os.environ["WINNIE_MODE"] = "local"
    uvicorn.run(
        "app.main:app",
        # Production must accept outside traffic; a laptop run must not.
        host="127.0.0.1" if args.local else "0.0.0.0",
        port=args.port,
        reload=args.local,
    )


if __name__ == "__main__":
    main()

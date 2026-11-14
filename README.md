# Winnie

Coordination agent for the NJIT Women in Computing Society (WiCS) e-board. See `CLAUDE.md` for the product spec.

| Service | Path | Stack |
|---|---|---|
| API + agent logic | `backend/` | Python 3.13, uv, FastAPI |
| DM interface | `messaging/` | Node, TypeScript, Photon (`@photon-ai/advanced-imessage`) |
| Web UI (placeholder) | `frontend/` | Vite, React, TypeScript |

Architecture: `docs/architecture.md`.

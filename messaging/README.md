# Winnie messaging sidecar

Node/TypeScript service that wraps [Photon](https://photon.codes) (iMessage DMs).
Photon has no Python SDK, so this sidecar handles the connection and forwards everything to the FastAPI backend.

```
iMessage <-> Photon <-> messaging/ (this) <-> backend /webhooks/messaging
                                   ^---- backend POST /send
```

```bash
npm install
cp .env.example .env
npm run dev        # once src/ has code
```

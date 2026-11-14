# HTTP client for the messaging/ sidecar (Node + Photon).
# Photon has no Python SDK, so outbound DMs go: backend -> POST {MESSAGING_SIDECAR_URL}/send -> Photon.
# Inbound DMs arrive at app.api.routes.webhooks (/webhooks/messaging).

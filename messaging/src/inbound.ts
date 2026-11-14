// Inbound DM -> backend.
// Normalise the Photon message (sender handle, text, thread id), sign it with
// MESSAGING_WEBHOOK_SECRET, and POST to BACKEND_WEBHOOK_URL (/webhooks/messaging).
// No business logic here: the backend decides what "done" / "blocked" means.

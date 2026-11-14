// Messaging sidecar: the ONLY job of this service is to move direct messages between Photon
// (iMessage) and the FastAPI backend. All business logic ("what does 'done' mean?") lives in
// backend/. Photon ships TypeScript SDKs only, which is why this Node service exists at all.
//
//   iMessage <-> Photon <-> messaging/ (this file) <-> backend /webhooks/messaging
//                                         ^---- backend calls POST /send
//
// Nothing is built yet. This single file is the whole service for now; split it only when it
// outgrows one screen. The sections below are the plan, in build order.
//
// Run (from messaging/): npm run dev
//
// ---------------------------------------------------------------------------------------------
// 1. CONFIG (env vars; fail fast at startup if a required one is missing)
//    PHOTON_API_KEY, PORT, BACKEND_WEBHOOK_URL, MESSAGING_WEBHOOK_SECRET.
//    MESSAGING_WEBHOOK_SECRET must match backend/.env. See .env.example.
//
// 2. PAYLOAD TYPES (the backend <-> sidecar contract)
//    Keep in sync with the messaging shapes in backend/app/schemas.py when those are added.
//
// 3. CONNECT TO PHOTON
//    Use @photon-ai/advanced-imessage. Confirm the real API, auth and inbound transport first.
//
// 4. INBOUND: iMessage -> backend
//    Subscribe to inbound messages. Normalise each one (sender handle, text, thread id), sign it
//    with MESSAGING_WEBHOOK_SECRET, and POST it to BACKEND_WEBHOOK_URL. No business logic here.
//
// 5. OUTBOUND: backend -> iMessage
//    Tiny HTTP server: POST /send {recipient handle, text, optional quick-reply hints} and
//    GET /health. Verify the request came from the backend, then send through Photon.
// ---------------------------------------------------------------------------------------------

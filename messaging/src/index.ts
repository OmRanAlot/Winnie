// Messaging sidecar entrypoint (Node + TypeScript).
//
// Why this exists: Photon ships TypeScript SDKs only, so this small service owns the Photon
// connection and the FastAPI backend owns all business logic.
//
// TODO:
//   - Load config (src/config.ts).
//   - Connect to Photon via @photon-ai/advanced-imessage.
//   - Start a tiny HTTP server exposing POST /send (called by backend) and GET /health.
//   - Subscribe to inbound messages -> src/inbound.ts.

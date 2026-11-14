# /webhooks — inbound events from other services.
# TODO:
#   POST /webhooks/messaging  from messaging/ (Photon DMs: "done", "blocked", questions).
#                             Verify the MESSAGING_WEBHOOK_SECRET signature before trusting the payload.
#   POST /webhooks/email      new shared-inbox mail (if the provider pushes)

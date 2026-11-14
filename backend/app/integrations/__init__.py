"""Thin clients for outside systems: auth, retries, plain data out. No business decisions here.

Services call these; routes never do. Keep every secret server-side. Define the interface and a
mock first, then the real client. Nothing is built yet.

PLANNED (create the file when you build the integration)
    google.py            Google Sheets (the existing task tracker: read + status write-back) and
                         Google Docs/Drive (meeting notes and agendas).
    discord_bot.py       Discord bot (discord.py): read task mentions in channels; optionally send
                         notifications.
    email_inbox.py       Shared-inbox client (provider TBD: Gmail API vs IMAP). Fetch new threads,
                         detect replies.
    messaging_sidecar.py HTTP client for messaging/ (the Node + Photon sidecar). Photon has no
                         Python SDK, so outbound DMs go: backend -> POST {MESSAGING_SIDECAR_URL}/send
                         -> Photon. Inbound DMs arrive at routes/webhooks.py. Confirm the Photon
                         transport before writing this.
    transcription.py     Server-side audio -> transcript, only if browser transcription proves
                         insufficient (provider TBD). The browser recorder already transcribes in
                         the page and sends the text with the audio (see routes/recordings.py).
"""

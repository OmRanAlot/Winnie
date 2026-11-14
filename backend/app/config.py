# Settings loaded from the environment / backend/.env via pydantic-settings.
#
# TODO: Settings model whose fields mirror backend/.env.example:
#   APP_ENV, LOG_LEVEL, FRONTEND_ORIGIN, DATABASE_URL,
#   GOOGLE_SERVICE_ACCOUNT_FILE, TASK_TRACKER_SHEET_ID, MEETING_NOTES_FOLDER_ID,
#   DISCORD_BOT_TOKEN, DISCORD_GUILD_ID,
#   SHARED_INBOX_ADDRESS (+ inbox credentials),
#   MESSAGING_SIDECAR_URL, MESSAGING_WEBHOOK_SECRET (shared with messaging/),
#   TRANSCRIPTION_API_KEY,
#   EMAIL_REMINDER_AFTER_HOURS, DEADLINE_WARNING_DAYS.
# Fail fast at startup when a required secret is missing.

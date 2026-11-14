# Scheduled jobs

Add a separate worker entry point for reminders, retries, and later inbox sweeps. Do not start a scheduler at FastAPI import time: reload and multiple API workers can duplicate sends. Start with one worker and durable notification deduplication.

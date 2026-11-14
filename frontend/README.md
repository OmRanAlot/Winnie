# Winnie conversation recorder

Browser-native recording (`MediaRecorder`) and live transcription (`SpeechRecognition` / `webkitSpeechRecognition`). No Gemini integration or API key is used. FastAPI only stores the completed audio/transcript JSON.

Start both services in separate terminals:

```bash
cd backend
uv run fastapi dev app/main.py
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Choose the spoken language, click **Start recording**, and allow microphone/speech access. Live words appear while recording. Click **Stop recording**, review playback, and edit the transcript.

- **Save & download JSON** sends the JSON through Vite's `/api` proxy to `POST /api/recordings`. The backend saves it under `backend/data/recordings/` (gitignored), and the browser downloads a copy.
- **Download locally** downloads without contacting the backend, including when the API is offline.

Browser speech recognition can use the browser vendor's online service. It is not guaranteed offline and availability varies by browser. Use localhost or HTTPS. Unsupported browsers, denied permission, and network errors show actionable messages while preserving audio. The app restarts recognition after silence, waits for final words on stop, and marks incomplete transcripts accordingly. Browser recognition cannot retrospectively transcribe captured audio; missing words can be entered manually.

The JSON contains `schemaVersion`, `title`, `startedAt`, `durationMs`, `transcription: { language, text, provider, status }`, and `audio: { mimeType, encoding: "base64", sizeBytes, data }`. Play exported audio with `data:${audio.mimeType};base64,${audio.data}`. Audio is limited to 10 MB per recording. Download or save before closing the page.

`VITE_API_BASE_URL` defaults to `/api`. For a separate backend host, include the path, e.g. `http://localhost:8000/api`. Production hosting must forward `/api` to FastAPI or configure this URL plus backend CORS.

Checks:

```bash
npm run build
node --experimental-strip-types --test tests/speech.test.mjs
```

Backend: `uv run pytest`. Speech tests simulate browser events (final/interim results, silence restart, network errors, unsupported browsers, and stop timeout); actual microphone capture and recognition accuracy must be tested interactively in the intended browser.

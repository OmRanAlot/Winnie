# Winnie conversation recorder

React + TypeScript frontend using browser getUserMedia, MediaRecorder, and Web Speech APIs. No backend or API key required.

```bash
npm install
npm run dev
```

Open http://localhost:5173, name the conversation, choose a language, and click **Start recording**. Allow microphone access, then **Stop recording** when finished. Listen back, edit the transcript, and **Download JSON**. Download before starting another recording or closing the page: recordings are held in memory, not persisted.

Microphone capture requires localhost or HTTPS. Live transcription requires SpeechRecognition or webkitSpeechRecognition support and may require internet access. The browser's speech service may receive audio. If recognition is unavailable or fails, audio capture remains available and the transcript can be entered manually. Only finalized recognition results are retained; review the transcript for omissions. This captures microphone input, not system audio, and does not identify speakers.

JSON fields:
- schemaVersion: 1
- title: conversation name
- startedAt: ISO timestamp
- durationMs: recording duration
- transcription: { language, text }
- audio: { mimeType, encoding: "base64", sizeBytes, data }

Audio is embedded as base64 so the JSON is self-contained. To play it elsewhere, construct `data:${audio.mimeType};base64,${audio.data}` as an audio element's source. Long recordings consume memory, and base64 increases file size.

```bash
npm run build
npm run preview
```

Manual verification: record a spoken sentence, stop, check playback, correct the transcript, download JSON, and verify its embedded audio plays. Also check denied microphone permission, unavailable recognition, and a second recording. Real microphone and speech-service behavior requires an interactive browser session.

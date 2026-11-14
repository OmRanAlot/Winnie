// The whole app: a single-page conversation recorder.
//
// Flow: record the microphone (MediaRecorder) while live-transcribing the speech
// (lib/speech.ts), let the user edit the transcript, then either
// The moment recording stops, autoSave() POSTs the audio + transcript to the backend (lib/api.ts
// -> backend POST /api/recordings, which writes the JSON and the audio file) in the background,
// with no click and nothing waiting on it. If that fails, it downloads both files locally.
// The buttons are for saving another copy after editing the transcript:
//   - "Save & download JSON": POST to the backend and also download the JSON + audio, or
//   - "Download locally": download the JSON + audio without contacting the backend.
// The JSON shape is defined by backend/app/schemas.py (Recording); keep them in sync.
//
// PLACEHOLDER: the UX team's design will replace this frontend, so don't invest here.
import { useEffect, useRef, useState } from 'react';
import { checkHealth, MAX_AUDIO_BYTES, saveRecording } from './lib/api';
import { browserRecognition, startTranscription, type TranscriptStatus } from './lib/speech';

type Phase = 'idle' | 'starting' | 'recording' | 'stopping' | 'ready';
interface Recording { audio: Blob; startedAt: string; durationMs: number; language: string }

function readAsBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => { const url = reader.result as string; resolve(url.slice(url.indexOf(',') + 1)); };
    reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob);
  });
}

async function buildRecordingJson(item: Recording, title: string, transcript: string, status: TranscriptStatus) {
  return {
    schemaVersion: 1, title: title.trim() || 'Untitled conversation', startedAt: item.startedAt, durationMs: item.durationMs,
    transcription: { language: item.language, text: transcript, provider: 'browser-speech-recognition', status },
    audio: { mimeType: item.audio.type, encoding: 'base64', sizeBytes: item.audio.size, data: await readAsBase64(item.audio) },
  };
}

function downloadFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const audioExtension = (mime: string) => ({ 'audio/webm': 'webm', 'audio/mp4': 'm4a', 'audio/ogg': 'ogg', 'audio/wav': 'wav', 'audio/mpeg': 'mp3' })[mime.split(';')[0]] ?? 'webm';
const clock = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [apiStatus, setApiStatus] = useState('Checking API…');
  const [title, setTitle] = useState('Untitled conversation');
  const [language, setLanguage] = useState('en-US');
  const [transcript, setTranscript] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState<TranscriptStatus>('unavailable');
  const [interim, setInterim] = useState('');
  const [recording, setRecording] = useState<Recording | null>(null);
  const [audioUrl, setAudioUrl] = useState('');
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const mounted = useRef(true);
  const capture = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const started = useRef(0);
  const speech = useRef<ReturnType<typeof startTranscription> | null>(null);
  const startPending = useRef(false);
  // Latest title/transcript for the automatic save, which runs from a recorder callback whose
  // closure would otherwise see stale state.
  const titleRef = useRef(title);
  const transcriptRef = useRef('');
  const busy = !['idle', 'ready'].includes(phase);
  const canRecord = !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    checkHealth(controller.signal).then(() => setApiStatus('API connected')).catch(() => {
      if (!controller.signal.aborted) setApiStatus('API offline · start the backend');
    });
    return () => {
      mounted.current = false; controller.abort(); speech.current?.dispose();
      if (capture.current?.state === 'recording') capture.current.stop();
      stream.current?.getTracks().forEach(track => track.stop());
    };
  }, []);
  useEffect(() => {
    if (!recording) { setAudioUrl(''); return; }
    const url = URL.createObjectURL(recording.audio); setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [recording]);
  useEffect(() => {
    if (phase !== 'recording') return;
    const timer = window.setInterval(() => setSeconds((Date.now() - started.current) / 1000), 250);
    return () => clearInterval(timer);
  }, [phase]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    if (busy || recording) window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [busy, recording]);

  function stop() {
    if (capture.current?.state !== 'recording') return;
    setPhase('stopping'); capture.current.stop();
    stream.current?.getTracks().forEach(track => track.stop());
  }

  async function start() {
    if (busy || startPending.current) return;
    if (recording && !window.confirm('Start another conversation? Download the current recording first if you want to keep it.')) return;
    startPending.current = true; setPhase('starting'); setError(''); setNotice('');
    try {
      const input = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { input.getTracks().forEach(track => track.stop()); return; }
      stream.current = input;
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(input, mimeType ? { mimeType } : undefined);
      capture.current = recorder;
      const chunks: Blob[] = []; let size = 0;
      recorder.ondataavailable = event => {
        if (event.data.size) { chunks.push(event.data); size += event.data.size; }
        // Stop below the API limit, allowing room for the final recorder chunk.
        if (size >= MAX_AUDIO_BYTES - 256 * 1024 && recorder.state === 'recording') stop();
      };
      recorder.onerror = () => { setError('Recording was interrupted. Captured audio has been kept.'); stop(); };
      recorder.onstop = async () => {
        input.getTracks().forEach(track => track.stop());
        if (!mounted.current) return;
        setPhase('stopping');
        const audio = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || 'audio/webm' });
        const item = { audio, startedAt: new Date(started.current).toISOString(), durationMs: Date.now() - started.current, language };
        setSeconds(item.durationMs / 1000);
        if (!audio.size) { speech.current?.dispose(); setError('No audio was captured. Check your microphone and try again.'); setPhase('idle'); return; }
        setRecording(item);
        const status = await speech.current?.stop();
        const finalStatus = status ?? 'unavailable';
        if (mounted.current) { setTranscriptStatus(finalStatus); setPhase('ready'); }
        void autoSave(item, finalStatus); // Runs in the background; nothing waits on it.
      };
      input.getAudioTracks().forEach(track => { track.onended = stop; });
      recorder.start(1000); started.current = Date.now();
      transcriptRef.current = ''; setRecording(null); setTranscript(''); setTranscriptStatus('unavailable'); setSeconds(0); setPhase('recording');
      speech.current = startTranscription(browserRecognition(), language,
        text => { transcriptRef.current = `${transcriptRef.current} ${text}`.trim(); setTranscript(transcriptRef.current); }, setInterim, setNotice);
    } catch (cause) {
      stream.current?.getTracks().forEach(track => track.stop());
      setError(cause instanceof DOMException && cause.name === 'NotAllowedError' ? 'Microphone access was denied. Allow access in browser settings and try again.' : `Could not start recording: ${cause instanceof Error ? cause.message : 'check your microphone.'}`);
      setPhase(recording ? 'ready' : 'idle');
    } finally { startPending.current = false; }
  }

  // Downloads the JSON and the audio file to this device.
  function downloadLocalCopy(item: Recording, json: unknown) {
    const base = `conversation-${item.startedAt.replace(/[:.]/g, '-')}`;
    downloadFile(new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' }), `${base}.json`);
    downloadFile(item.audio, `${base}.${audioExtension(item.audio.type)}`);
  }

  // Runs as soon as a recording stops. Saves the JSON and the audio file on the backend without
  // any click or waiting. If the backend can't be reached, the files are downloaded to this
  // device instead so nothing is lost.
  async function autoSave(item: Recording, status: TranscriptStatus) {
    let json: unknown;
    try {
      json = await buildRecordingJson(item, titleRef.current, transcriptRef.current, status);
      const saved = await saveRecording(json);
      if (!mounted.current) return;
      setNotice(`Saved automatically: ${saved.filename} and ${saved.audioFilename}`); setApiStatus('API connected');
    } catch (cause) {
      if (!mounted.current) return;
      const reason = cause instanceof Error ? cause.message : 'Could not save to the backend.';
      if (json) { downloadLocalCopy(item, json); setError(`${reason} Downloaded the JSON and audio to this device instead.`); }
      else setError(`${reason} Use "Download locally" to keep this recording.`);
    }
  }

  async function download(saveToBackend: boolean) {
    if (!recording) return;
    setSaving(true); setError('');
    try {
      const json = await buildRecordingJson(recording, title, transcript, transcriptStatus);
      if (saveToBackend) {
        const saved = await saveRecording(json);
        setNotice(`Saved to backend: ${saved.filename} and ${saved.audioFilename}`); setApiStatus('API connected');
      }
      downloadLocalCopy(recording, json);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save. Try downloading locally.'); }
    finally { setSaving(false); }
  }

  return <div className="app">
    <header><a className="brand" href="/">winnie<span>•</span></a><span role="status">{apiStatus}</span></header>
    <main>
      <div className="eyebrow">THE CONVERSATION SPACE</div>
      <h1>Be here.<br /><span>We’ll keep the words.</span></h1>
      <p className="intro">Record and transcribe with your browser, then save the audio and words together.</p>
      <section className="workspace" aria-label="Conversation recorder">
        <div className="record-panel">
          <label htmlFor="title">CONVERSATION NAME</label><input id="title" value={title} maxLength={120} onChange={e => { titleRef.current = e.target.value; setTitle(e.target.value); }} />
          <div className={`orb ${phase === 'recording' ? 'active' : ''}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg></div>
          <div className="timer">{clock(seconds)}</div>
          <p className="status" role="status">{({ idle: 'Ready when you are', starting: 'Waiting for microphone…', recording: 'Recording your conversation', stopping: 'Finishing recording…', ready: 'Your audio is ready' })[phase]}</p>
          <select aria-label="Transcription language" disabled={busy} value={language} onChange={e => setLanguage(e.target.value)}><option value="en-US">English</option><option value="es-ES">Spanish</option><option value="fr-FR">French</option><option value="ar-SA">Arabic</option></select>
          {phase === 'recording' ? <button className="primary stop" onClick={stop}>■ Stop recording</button> : <button className="primary" disabled={!canRecord || busy} onClick={() => void start()}>● {recording ? 'Record another conversation' : 'Start recording'}</button>}
          <p className="small">Make sure everyone agrees to be recorded.</p>
        </div>
        <div className="transcript-panel"><div className="panel-heading"><h2>Transcript</h2><span className="badge">{phase === 'recording' ? 'LIVE' : 'BROWSER TRANSCRIPT'}</span></div>
          <textarea aria-label="Conversation transcript" readOnly={busy} value={transcript} onChange={e => { transcriptRef.current = e.target.value; setTranscript(e.target.value); setTranscriptStatus('manual'); }} placeholder="Your words appear here as you speak. Review and edit the transcript after recording." />
          <p className="interim" aria-live="polite">{interim}</p>
          <div className="transcript-footer"><span>{transcript.trim() ? transcript.trim().split(/\s+/).length : 0} words</span><span>Editable after recording</span></div>
        </div>
      </section>
      {!browserRecognition() && <p className="message">Speech recognition is unavailable in this browser. You can record audio and enter a transcript manually.</p>}
      {!canRecord && <p className="message error" role="alert">Microphone recording requires localhost or HTTPS and a browser with MediaRecorder support.</p>}
      {error && <p className="message error" role="alert">{error}</p>}{notice && <p className="message" role="status">{notice}</p>}
      <section className="export-panel"><div><h2>A conversation to keep.</h2><p>Audio + transcript. One JSON file.</p>{audioUrl && <audio controls src={audioUrl} aria-label="Recording playback" />}</div><button className="download" disabled={!recording || busy || saving} onClick={() => void download(true)}>{saving ? 'Preparing…' : 'Save & download JSON'}</button><button className="download" disabled={!recording || busy || saving} onClick={() => void download(false)}>Download locally</button></section>
      <p className="privacy">Recording and transcription use your browser's built-in APIs. Speech recognition may use your browser vendor's online service. When you stop recording, the JSON and the audio file are saved to the backend automatically. If the backend is offline, they download to your device instead. The buttons below save another copy, for example after you edit the transcript. Up to 10 MB of audio per recording.</p>
    </main><footer><span>Made for the moments worth remembering.</span><span>WINNIE / CONVERSATIONS</span></footer>
  </div>;
}

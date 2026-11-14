import { useEffect, useRef, useState } from 'react';
import { checkHealth, MAX_AUDIO_BYTES, saveRecording } from './lib/api';
import { browserRecognition, startTranscription, type TranscriptStatus } from './lib/speech';

type Phase = 'idle' | 'starting' | 'recording' | 'stopping' | 'ready';
interface Recording { audio: Blob; startedAt: string; durationMs: number; language: string }
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
        if (mounted.current) { setTranscriptStatus(status ?? 'unavailable'); setPhase('ready'); }
      };
      input.getAudioTracks().forEach(track => { track.onended = stop; });
      recorder.start(1000); started.current = Date.now();
      setRecording(null); setTranscript(''); setTranscriptStatus('unavailable'); setSeconds(0); setPhase('recording');
      speech.current = startTranscription(browserRecognition(), language,
        text => setTranscript(previous => `${previous} ${text}`.trim()), setInterim, setNotice);
    } catch (cause) {
      stream.current?.getTracks().forEach(track => track.stop());
      setError(cause instanceof DOMException && cause.name === 'NotAllowedError' ? 'Microphone access was denied. Allow access in browser settings and try again.' : `Could not start recording: ${cause instanceof Error ? cause.message : 'check your microphone.'}`);
      setPhase(recording ? 'ready' : 'idle');
    } finally { startPending.current = false; }
  }

  async function download(saveToBackend: boolean) {
    if (!recording) return;
    setSaving(true); setError('');
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(reader.error); reader.readAsDataURL(recording.audio);
      });
      const json = {
        schemaVersion: 1, title: title.trim() || 'Untitled conversation', startedAt: recording.startedAt, durationMs: recording.durationMs,
        transcription: { language: recording.language, text: transcript, provider: 'browser-speech-recognition', status: transcriptStatus },
        audio: { mimeType: recording.audio.type, encoding: 'base64', sizeBytes: recording.audio.size, data: dataUrl.slice(dataUrl.indexOf(',') + 1) },
      };
      if (saveToBackend) {
        const filename = await saveRecording(json);
        setNotice(`Saved to backend: ${filename}`); setApiStatus('API connected');
      }
      const url = URL.createObjectURL(new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url;
      link.download = `conversation-${recording.startedAt.replace(/[:.]/g, '-')}.json`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
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
          <label htmlFor="title">CONVERSATION NAME</label><input id="title" value={title} maxLength={120} onChange={e => setTitle(e.target.value)} />
          <div className={`orb ${phase === 'recording' ? 'active' : ''}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg></div>
          <div className="timer">{clock(seconds)}</div>
          <p className="status" role="status">{({ idle: 'Ready when you are', starting: 'Waiting for microphone…', recording: 'Recording your conversation', stopping: 'Finishing recording…', ready: 'Your audio is ready' })[phase]}</p>
          <select aria-label="Transcription language" disabled={busy} value={language} onChange={e => setLanguage(e.target.value)}><option value="en-US">English</option><option value="es-ES">Spanish</option><option value="fr-FR">French</option><option value="ar-SA">Arabic</option></select>
          {phase === 'recording' ? <button className="primary stop" onClick={stop}>■ Stop recording</button> : <button className="primary" disabled={!canRecord || busy || saving} onClick={() => void start()}>● {recording ? 'Record another conversation' : 'Start recording'}</button>}
          <p className="small">Make sure everyone agrees to be recorded.</p>
        </div>
        <div className="transcript-panel"><div className="panel-heading"><h2>Transcript</h2><span className="badge">{phase === 'recording' ? 'LIVE' : 'BROWSER TRANSCRIPT'}</span></div>
          <textarea aria-label="Conversation transcript" readOnly={busy} value={transcript} onChange={e => { setTranscript(e.target.value); setTranscriptStatus('manual'); }} placeholder="Your words appear here as you speak. Review and edit the transcript after recording." />
          <p className="interim" aria-live="polite">{interim}</p>
          <div className="transcript-footer"><span>{transcript.trim() ? transcript.trim().split(/\s+/).length : 0} words</span><span>Editable after recording</span></div>
        </div>
      </section>
      {!browserRecognition() && <p className="message">Speech recognition is unavailable in this browser. You can record audio and enter a transcript manually.</p>}
      {!canRecord && <p className="message error" role="alert">Microphone recording requires localhost or HTTPS and a browser with MediaRecorder support.</p>}
      {error && <p className="message error" role="alert">{error}</p>}{notice && <p className="message" role="status">{notice}</p>}
      <section className="export-panel"><div><h2>A conversation to keep.</h2><p>Audio + transcript. One JSON file.</p>{audioUrl && <audio controls src={audioUrl} aria-label="Recording playback" />}</div><button className="download" disabled={!recording || busy || saving} onClick={() => void download(true)}>{saving ? 'Preparing…' : 'Save & download JSON'}</button><button className="download" disabled={!recording || busy || saving} onClick={() => void download(false)}>Download locally</button></section>
      <p className="privacy">Recording and transcription use your browser's built-in APIs. Speech recognition may use your browser vendor's online service. Save & download stores the JSON on the backend; Download locally only saves to your device. Up to 10 MB of audio per recording.</p>
    </main><footer><span>Made for the moments worth remembering.</span><span>WINNIE / CONVERSATIONS</span></footer>
  </div>;
}

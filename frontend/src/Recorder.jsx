// Meeting recorder for the Meetings screen: records the microphone, transcribes live in the
// browser (lib/speech.ts), saves audio + transcript to POST /api/recordings, then asks the backend
// to extract proposed tasks (POST /api/recordings/{id}/assignments). Proposed tasks are shown for
// review only; nothing is added to the task list automatically.
import { useEffect, useRef, useState } from "react";
import { assignRecordingTasks, saveRecording } from "./lib/api.js";
import { browserRecognition, startTranscription } from "./lib/speech.ts";

const MAX_AUDIO_BYTES = 10 * 1024 * 1024; // backend limit (schemas.MAX_AUDIO_BYTES)
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export default function Recorder({ kind, onClose, onSaved = async () => {} }) {
  // idle -> recording -> saving -> assigning -> done | error
  const [phase, setPhase] = useState("idle");
  const [seconds, setSeconds] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [tasks, setTasks] = useState(null);
  const text = useRef("");
  const media = useRef(null);
  const speech = useRef(null);
  const started = useRef(0);

  useEffect(() => {
    if (phase !== "recording") return undefined;
    const timer = setInterval(() => setSeconds((Date.now() - started.current) / 1000), 250);
    return () => clearInterval(timer);
  }, [phase]);
  useEffect(() => () => { // stop the microphone if the dialog closes mid-recording
    speech.current?.dispose();
    if (media.current?.recorder.state === "recording") media.current.recorder.stop();
    media.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  async function start() {
    setError(""); setNotice(""); text.current = ""; setTranscript("");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setError(e?.name === "NotAllowedError" ? "Microphone access was denied. Allow it in the browser and try again." : `Could not start the microphone: ${e?.message || e}`);
      setPhase("error");
      return;
    }
    const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((m) => MediaRecorder.isTypeSupported(m));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    let size = 0;
    recorder.ondataavailable = (e) => {
      if (e.data.size) { chunks.push(e.data); size += e.data.size; }
      if (size >= MAX_AUDIO_BYTES - 256 * 1024 && recorder.state === "recording") stop(); // stay under the limit
    };
    recorder.onstop = () => finish(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
    media.current = { recorder, stream };
    recorder.start(1000);
    started.current = Date.now();
    setSeconds(0);
    setPhase("recording");
    speech.current = startTranscription(browserRecognition(), "en-US",
      (words) => { text.current = `${text.current} ${words}`.trim(); setTranscript(text.current); },
      setInterim, setNotice);
  }

  function stop() {
    if (media.current?.recorder.state === "recording") media.current.recorder.stop();
    media.current?.stream.getTracks().forEach((t) => t.stop());
  }

  async function finish(audio) {
    const durationMs = Date.now() - started.current;
    const status = (await speech.current?.stop()) ?? "unavailable";
    if (!audio.size) { setError("No audio was captured. Check your microphone."); setPhase("error"); return; }
    setPhase("saving");
    try {
      const recording = {
        schemaVersion: 1,
        title: `${kind} meeting ${new Date(started.current).toLocaleDateString()}`,
        startedAt: new Date(started.current).toISOString(),
        durationMs,
        transcription: { language: "en-US", text: text.current, provider: "browser-speech-recognition", status },
        audio: { mimeType: audio.type, encoding: "base64", sizeBytes: audio.size, data: await toBase64(audio) },
      };
      const saved = await saveRecording(recording);
      if (!text.current.trim()) { setNotice("Saved, but no words were transcribed, so there are no tasks to extract."); setPhase("done"); setTasks([]); return; }
      setPhase("assigning");
      setTasks(await assignRecordingTasks(saved.id, recording));
      try { await onSaved(); } catch { setNotice('Tasks were saved, but the board could not refresh. Please refresh it.'); }
      setPhase("done");
    } catch (e) {
      setError(e.message);
      setPhase("error");
    }
  }

  const busy = phase === "saving" || phase === "assigning";
  return (
    <div className="modal"><div className="box" style={{ maxWidth: 640, width: "90%", textAlign: "left" }}>
      <h4 style={{ textAlign: "center" }}>{kind} meeting recording</h4>
      <p style={{ textAlign: "center", fontSize: 32, margin: "6px 0", fontWeight: 800 }}>{clock(seconds)}</p>
      <p style={{ textAlign: "center", margin: "0 0 10px" }}>{{
        idle: "Make sure everyone agrees to be recorded.", recording: "Recording… speak normally.",
        saving: "Saving the recording…", assigning: "Finding tasks in the transcript (can take up to a minute)…",
        done: "Done.", error: "Something went wrong.",
      }[phase]}</p>
      {(phase === "recording" || transcript) && <div className="panel" style={{ maxHeight: 160, overflow: "auto", fontSize: 15, padding: "12px 16px" }}>
        {transcript || <i>Words appear here as you speak…</i>} <span style={{ opacity: 0.6 }}>{interim}</span></div>}
      {notice && <p style={{ fontSize: 14 }}>{notice}</p>}
      {error && <p role="alert" style={{ color: "#c0392b", fontSize: 15 }}>{error}</p>}
      {tasks && tasks.length > 0 && <div style={{ marginTop: 10 }}><b>Tasks saved from this recording (review flagged assignments):</b>
        <ul style={{ fontSize: 15, lineHeight: 1.5, paddingLeft: 20 }}>{tasks.map((t, i) => (
          <li key={i}><b>{t.title}</b> → {t.assignee || "Unassigned"} ({t.seat}){t.deadline ? `, ${t.deadline}` : ""}{t.needs_review ? " ⚠ needs review" : ""}</li>))}</ul></div>}
      {tasks && tasks.length === 0 && phase === "done" && !notice && <p>No tasks were found in this meeting.</p>}
      <div className="acts">
        {phase === "idle" && <button className="btn" onClick={start}>● Start recording</button>}
        {phase === "recording" && <button className="btn" onClick={stop}>■ Stop</button>}
        {(phase === "done" || phase === "error") && <button className="btn alt" onClick={() => { setPhase("idle"); setTasks(null); setSeconds(0); }}>Record another</button>}
        <button className="btn out" disabled={busy || phase === "recording"} onClick={onClose}>Close</button>
      </div>
    </div></div>
  );
}

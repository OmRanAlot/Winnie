// React hook that records the microphone (MediaRecorder) while live-transcribing the speech
// (lib/speech.js). When recording stops it calls onComplete(recording) exactly once with
//   { title, audio: Blob, startedAt, durationMs, language, transcript, status }
// and the caller uploads it (see lib/recordingUpload.js). Recording stops by itself just under the
// API's audio size limit.
import { useCallback, useEffect, useRef, useState } from 'react';
import { MAX_AUDIO_BYTES } from './api';
import { browserRecognition, startTranscription } from './speech';

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
const SIZE_HEADROOM_BYTES = 256 * 1024; // room for the final recorder chunk

export function canRecordAudio() {
  return !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
}

function startError(cause) {
  if (cause instanceof DOMException && cause.name === 'NotAllowedError') {
    return 'Microphone access was denied. Allow access in browser settings and try again.';
  }
  return `Could not start recording: ${cause instanceof Error ? cause.message : 'check your microphone.'}`;
}

/** @param {{ language?: string, onComplete: (recording: object) => void, onNotice?: (text: string) => void }} options */
export function useRecorder({ language = 'en-US', onComplete, onNotice }) {
  const [phase, setPhase] = useState('idle'); // idle | starting | recording | stopping
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const recorder = useRef(null);
  const stream = useRef(null);
  const speech = useRef(null);
  const startedAt = useRef(0);
  const transcript = useRef('');
  const mounted = useRef(true);
  const latest = useRef({ onComplete, onNotice });
  latest.current = { onComplete, onNotice };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      speech.current?.dispose();
      if (recorder.current?.state === 'recording') recorder.current.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (phase !== 'recording') return undefined;
    const timer = window.setInterval(() => setSeconds((Date.now() - startedAt.current) / 1000), 250);
    return () => clearInterval(timer);
  }, [phase]);

  const stop = useCallback(() => {
    if (recorder.current?.state !== 'recording') return;
    setPhase('stopping');
    recorder.current.stop();
    stream.current?.getTracks().forEach((track) => track.stop());
  }, []);

  const start = useCallback(async (title) => {
    if (phase !== 'idle') return;
    setPhase('starting'); setError('');
    try {
      const input = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { input.getTracks().forEach((track) => track.stop()); return; }
      stream.current = input;
      const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
      const media = new MediaRecorder(input, mimeType ? { mimeType } : undefined);
      recorder.current = media;
      const chunks = [];
      let size = 0;
      media.ondataavailable = (event) => {
        if (event.data.size) { chunks.push(event.data); size += event.data.size; }
        if (size >= MAX_AUDIO_BYTES - SIZE_HEADROOM_BYTES && media.state === 'recording') stop();
      };
      media.onerror = () => { setError('Recording was interrupted. Captured audio has been kept.'); stop(); };
      media.onstop = async () => {
        input.getTracks().forEach((track) => track.stop());
        if (!mounted.current) return;
        setPhase('stopping');
        const audio = new Blob(chunks, { type: media.mimeType || chunks[0]?.type || 'audio/webm' });
        const durationMs = Date.now() - startedAt.current;
        if (!audio.size) {
          speech.current?.dispose();
          setError('No audio was captured. Check your microphone and try again.');
          setPhase('idle');
          return;
        }
        const status = (await speech.current?.stop()) ?? 'unavailable';
        if (!mounted.current) return;
        setSeconds(durationMs / 1000);
        setPhase('idle');
        latest.current.onComplete({
          title, audio, language, status, durationMs,
          startedAt: new Date(startedAt.current).toISOString(), transcript: transcript.current,
        });
      };
      input.getAudioTracks().forEach((track) => { track.onended = stop; });
      media.start(1000);
      startedAt.current = Date.now(); transcript.current = ''; setSeconds(0); setPhase('recording');
      speech.current = startTranscription(
        browserRecognition(), language,
        (text) => { transcript.current = `${transcript.current} ${text}`.trim(); },
        () => {}, (text) => latest.current.onNotice?.(text),
      );
    } catch (cause) {
      stream.current?.getTracks().forEach((track) => track.stop());
      setError(startError(cause));
      setPhase('idle');
    }
  }, [phase, language, stop]);

  return { phase, seconds, error, start, stop, canRecord: canRecordAudio() };
}

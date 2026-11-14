// Sends a finished recording to the backend: build the JSON the API expects (shape defined by
// backend/app/schemas/api.py Recording), POST it, then ask the backend to extract and store tasks.
// If the backend can't be reached the JSON and audio are downloaded instead, so nothing is lost.
import { assignTasks, saveRecording } from './api';

function readAsBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => { const url = reader.result; resolve(url.slice(url.indexOf(',') + 1)); };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function buildRecordingJson(recording) {
  return {
    schemaVersion: 1,
    title: recording.title.trim() || 'Untitled conversation',
    startedAt: recording.startedAt,
    durationMs: recording.durationMs,
    transcription: { language: recording.language, text: recording.transcript, provider: 'browser-speech-recognition', status: recording.status },
    audio: { mimeType: recording.audio.type, encoding: 'base64', sizeBytes: recording.audio.size, data: await readAsBase64(recording.audio) },
  };
}

const AUDIO_EXTENSIONS = { 'audio/webm': 'webm', 'audio/mp4': 'm4a', 'audio/ogg': 'ogg', 'audio/wav': 'wav', 'audio/mpeg': 'mp3' };

function downloadFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadLocalCopy(recording, json) {
  const base = `conversation-${recording.startedAt.replace(/[:.]/g, '-')}`;
  downloadFile(new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' }), `${base}.json`);
  downloadFile(recording.audio, `${base}.${AUDIO_EXTENSIONS[recording.audio.type.split(';')[0]] ?? 'webm'}`);
}

/**
 * Saves the recording, then extracts its tasks.
 * Resolves { saved, assignments, stored, storeError, assignError }:
 *   - throws only when the recording itself could not be saved (a local copy is downloaded first);
 *   - a task-extraction failure is reported in `assignError` because the recording is already safe.
 */
export async function submitRecording(recording) {
  const json = await buildRecordingJson(recording);
  let saved;
  try { saved = await saveRecording(json); }
  catch (cause) {
    downloadLocalCopy(recording, json);
    const reason = cause instanceof Error ? cause.message : 'Could not save to the backend.';
    throw new Error(`${reason} Downloaded the JSON and audio to this device instead.`);
  }
  try {
    const result = await assignTasks(saved.id);
    return {
      saved, assignments: result.data.assignments ?? [],
      stored: result.meta?.stored !== false, storeError: result.meta?.store_error ?? null, assignError: null,
    };
  } catch (cause) {
    return { saved, assignments: [], stored: false, storeError: null, assignError: cause instanceof Error ? cause.message : 'Task assignment failed' };
  }
}

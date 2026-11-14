// Live speech-to-text using the browser's built-in SpeechRecognition API (no API key, no backend).
// startTranscription() keeps recognition running through silences, reports final and interim
// words, and returns a session whose stop() resolves with a TranscriptStatus once the last
// words arrive. Browser support varies and some browsers send audio to their vendor's service.
// Used by Recorder.jsx (the Meetings screen). Restored from the original recorder.
export interface Recognition {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
export type RecognitionConstructor = new () => Recognition;
export type TranscriptStatus = 'completed' | 'partial' | 'unavailable' | 'manual';

export function browserRecognition(): RecognitionConstructor | undefined {
  const browser = window as Window & { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
}

export function startTranscription(
  Constructor: RecognitionConstructor | undefined,
  language: string,
  onFinal: (text: string) => void,
  onInterim: (text: string) => void,
  onNotice: (text: string) => void,
) {
  let speech: Recognition | undefined;
  let active = true;
  let failed = false;
  let heardSpeech = false;
  let ended = false;
  let restart: ReturnType<typeof setTimeout> | undefined;
  let finish: (() => void) | undefined;
  const fail = (message: string) => { failed = true; onNotice(message); };
  const detach = () => {
    if (speech) { speech.onresult = null; speech.onerror = null; speech.onend = null; }
    onInterim('');
  };
  if (!Constructor) fail('This browser has no speech recognition. Audio will still be recorded; enter the transcript manually or use a supported browser.');
  else {
    try {
      speech = new Constructor();
      speech.continuous = true; speech.interimResults = true; speech.lang = language;
      speech.onresult = event => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            const text = result[0].transcript.trim();
            if (text) { heardSpeech = true; onFinal(text); }
          } else interim += result[0].transcript;
        }
        onInterim(interim);
      };
      speech.onerror = event => {
        if (event.error === 'no-speech' || (!active && event.error === 'aborted')) return;
        const explanation: Record<string, string> = {
          'not-allowed': 'Speech recognition permission was denied. Allow microphone access and start a new recording.',
          'service-not-allowed': 'Your browser disabled its speech service. Check browser settings or try another supported browser.',
          network: 'The browser speech service could not connect. Check your internet connection and start a new recording.',
          'audio-capture': 'Speech recognition could not access the microphone.',
          'language-not-supported': 'The browser does not support this transcription language.',
        };
        fail(`${explanation[event.error] ?? `Browser transcription stopped (${event.error}).`} Audio recording is preserved.`);
      };
      speech.onend = () => {
        ended = true; onInterim('');
        if (finish) { finish(); return; }
        // Browsers may end a continuous session after silence. Restart while recording.
        if (active && !failed) restart = setTimeout(() => {
          if (!active) return;
          try { ended = false; speech!.start(); }
          catch { ended = true; fail('Browser transcription could not restart. Audio recording continues.'); }
        }, 250);
      };
      speech.start();
    } catch { ended = true; fail('Browser transcription could not start. Audio recording continues.'); }
  }
  return {
    async stop(): Promise<TranscriptStatus> {
      active = false; clearTimeout(restart);
      if (speech && !ended) await new Promise<void>(resolve => {
        const timeout = setTimeout(() => {
          failed = true;
          onNotice('The browser did not finish its last words in time. Review the transcript for omissions.');
          finish?.();
        }, 2000);
        finish = () => { clearTimeout(timeout); resolve(); };
        try { speech!.stop(); } catch { finish(); }
      });
      detach();
      try { speech?.abort(); } catch { /* Already ended. */ }
      if (!heardSpeech) {
        if (!failed) onNotice('No speech was recognized. Check playback and microphone input, or enter a transcript manually.');
        return 'unavailable';
      }
      return failed ? 'partial' : 'completed';
    },
    dispose() {
      active = false; clearTimeout(restart); finish?.(); detach();
      try { speech?.abort(); } catch { /* Already ended. */ }
    },
  };
}

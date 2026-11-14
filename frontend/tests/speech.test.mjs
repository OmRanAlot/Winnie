import assert from 'node:assert/strict';
import { test } from 'node:test';
import { startTranscription } from '../src/lib/speech.ts';

class FakeRecognition {
  static instance;
  starts = 0;
  constructor() { FakeRecognition.instance = this; }
  start() { this.starts++; }
  stop() { this.onend?.(); }
  abort() {}
}
const setup = (Constructor = FakeRecognition) => {
  const final = [], interim = [], notices = [];
  const session = startTranscription(Constructor, 'en-US', t => final.push(t), t => interim.push(t), t => notices.push(t));
  return { session, recognition: FakeRecognition.instance, final, interim, notices };
};

test('keeps final results once, displays interim speech, and drains final results on stop', async () => {
  const { session, recognition, final, interim } = setup();
  recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'Hello Winnie' } }, { isFinal: false, 0: { transcript: 'next meeting' } }] });
  recognition.onresult({ resultIndex: 1, results: [{ isFinal: true, 0: { transcript: 'Hello Winnie' } }, { isFinal: true, 0: { transcript: 'next meeting Tuesday' } }] });
  recognition.stop = () => {
    recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'Goodbye' } }] });
    recognition.onend();
  };
  assert.equal(await session.stop(), 'completed');
  assert.deepEqual(final, ['Hello Winnie', 'next meeting Tuesday', 'Goodbye']);
  assert.ok(interim.includes('next meeting'));
});

test('restarts recognition after silence, but never after stopping', async () => {
  const { session, recognition } = setup();
  recognition.onend();
  await new Promise(r => setTimeout(r, 300));
  assert.equal(recognition.starts, 2);
  await session.stop();
  await new Promise(r => setTimeout(r, 300));
  assert.equal(recognition.starts, 2);
});

test('network errors preserve a partial transcript and do not restart', async () => {
  const { session, recognition, final, notices } = setup();
  recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'Keep this' } }] });
  recognition.onerror({ error: 'network' }); recognition.onend();
  assert.equal(await session.stop(), 'partial');
  assert.deepEqual(final, ['Keep this']);
  assert.match(notices[0], /could not connect/);
  assert.equal(recognition.starts, 1);
});

test('unsupported browsers report unavailable instead of claiming success', async () => {
  const notices = [];
  const session = startTranscription(undefined, 'en-US', () => {}, () => {}, t => notices.push(t));
  assert.equal(await session.stop(), 'unavailable');
  assert.match(notices[0], /no speech recognition/);
});

test('a finalization timeout reports partial and releases the speech service', async () => {
  const { session, recognition, notices } = setup();
  recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'Already saved' } }] });
  recognition.stop = () => {};
  assert.equal(await session.stop(), 'partial');
  assert.match(notices[0], /did not finish/);
  assert.equal(recognition.onresult, null);
});

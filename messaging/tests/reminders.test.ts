import assert from "node:assert/strict";
import test from "node:test";
import { reminderCycle, type ReminderApi } from "../src/reminders.js";

const delivery = {
  id: "delivery-1", claim_token: "claim-1", transport: "photon" as const,
  recipient: "+15555550123", text: "Synthetic deadline reminder",
};

test("normal dispatch sends once then acknowledges the provider message ID", async () => {
  let scans: boolean[] = [], sends = 0;
  const acknowledgements: unknown[] = [];
  const api: ReminderApi = {
    next: async scan => { scans.push(scan); return { delivery: scans.length === 1 ? delivery : null }; },
    result: async (_, result) => { acknowledgements.push(result); },
  };
  const counts = await reminderCycle(api, async () => { sends++; return "provider-1"; });
  assert.equal(sends, 1);
  assert.deepEqual(scans, [true, false]);
  assert.deepEqual(acknowledgements, [{ outcome: "sent", provider_message_id: "provider-1" }]);
  assert.equal(counts.provider_accepted, 1);
});

test("acknowledgement failures and repeated payloads never repeat a physical send", async () => {
  let requests = 0, sends = 0, acknowledgements = 0;
  const cache = new Map();
  const api: ReminderApi = {
    next: async () => ({ delivery: requests++ % 2 === 0 ? delivery : null }),
    result: async () => { acknowledgements++; throw new Error("lost ack"); },
  };
  const send = async () => { sends++; return "provider-1"; };
  assert.equal((await reminderCycle(api, send, cache)).ack_failed, 1);
  api.result = async () => { acknowledgements++; };
  await reminderCycle(api, send, cache);
  assert.equal(sends, 1);
  assert.equal(acknowledgements, 4);
});

test("a provider timeout is uncertain and is not retried", async () => {
  let requests = 0, sends = 0;
  const acknowledgements: unknown[] = [];
  const api: ReminderApi = {
    next: async () => ({ delivery: requests++ < 2 ? delivery : null }),
    result: async (_, outcome) => { acknowledgements.push(outcome); },
  };
  await reminderCycle(api, async () => { sends++; throw new Error("timeout after acceptance"); });
  assert.equal(sends, 1);
  assert.deepEqual(acknowledgements, [{ outcome: "uncertain" }, { outcome: "uncertain" }]);
});

test("mock cycles and disabled backend never call Photon", async () => {
  const api: ReminderApi = {
    next: async () => ({ delivery: null, mock_processed: 3 }), result: async () => {},
  };
  const counts = await reminderCycle(api, async () => { assert.fail("Must not send"); });
  assert.equal(counts.mock_processed, 3);
});

test("unexpected mock payload cannot be sent as Photon", async () => {
  const api: ReminderApi = {
    next: async () => ({ delivery: { ...delivery, transport: "mock" } as any }),
    result: async () => {},
  };
  await assert.rejects(reminderCycle(api, async () => { assert.fail("Must not send"); }), /Invalid reminder/);
});

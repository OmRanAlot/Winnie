import assert from "node:assert/strict";
import test from "node:test";
import { helpCycle, type HelpDelivery } from "../src/help.js";

const group: HelpDelivery = { id: "item-1", claim_token: "token-1", kind: "group",
  recipient: "+15555550123", second_recipient: "+15555550124", text: "Handoff" };

test("group creation executes once even if the receipt needs retrying", async () => {
  let calls = 0, creates = 0, acks = 0;
  await helpCycle({ next: async () => ({ delivery: calls++ === 0 ? group : null }),
    result: async (_, result) => { assert.equal(result.provider_id, "group-id"); if (++acks < 3) throw Error(); } },
    async () => { creates++; return "group-id"; });
  assert.equal(creates, 1); assert.equal(acks, 3);
});

test("an uncertain group action is not retried", async () => {
  let calls = 0, creates = 0;
  await helpCycle({ next: async () => ({ delivery: calls++ === 0 ? group : null }),
    result: async (_, result) => { assert.equal(result.outcome, "uncertain"); } },
    async () => { creates++; throw Error("provider timeout"); });
  assert.equal(creates, 1);
});

test("invalid group participants never reach Photon", async () => {
  let creates = 0;
  await assert.rejects(helpCycle({ next: async () => ({ delivery: { ...group, second_recipient: group.recipient } }),
    result: async () => {} }, async () => { creates++; return "group-id"; }));
  assert.equal(creates, 0);
});

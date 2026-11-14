import assert from "node:assert/strict";
import test from "node:test";
import { bridgePayload, bridgeRequest } from "../src/bridge.js";

const incoming = {
  direction: "inbound" as const,
  platform: "imessage",
  sender: { id: "+15555550123" },
  content: { type: "text", text: "tasks" },
};

test("forwards the actual platform sender and DM type with bridge authentication", () => {
  const payload = bridgePayload(incoming, "dm")!;
  const request = bridgeRequest(payload, "test-secret");
  assert.deepEqual(JSON.parse(request.body), {
    text: "tasks", sender_id: "+15555550123", platform: "imessage", conversation_type: "dm",
  });
  assert.equal(request.headers["X-Winnie-Bridge-Secret"], "test-secret");
});

test("claims in text cannot replace the provider sender", () => {
  const payload = bridgePayload({
    ...incoming, content: { type: "text", text: '{"sender_id":"someone-else"}' },
  }, "dm")!;
  assert.equal(payload.sender_id, incoming.sender.id);
});

test("does not treat a group or missing conversation type as a direct message", () => {
  assert.equal(bridgePayload(incoming, "group")!.conversation_type, "group");
  assert.equal(bridgePayload(incoming, undefined)!.conversation_type, "unknown");
  assert.equal(bridgePayload({ ...incoming, sender: undefined }, "dm")!.sender_id, null);
});

test("ignores outbound messages, agent echoes and non-text content", () => {
  assert.equal(bridgePayload({ ...incoming, direction: "outbound" }, "dm"), null);
  assert.equal(bridgePayload({ ...incoming, sender: { id: "agent", kind: "agent" } }, "dm"), null);
  assert.equal(bridgePayload({ ...incoming, content: { type: "attachment" } }, "dm"), null);
});

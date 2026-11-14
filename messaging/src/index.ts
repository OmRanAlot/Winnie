import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { bridgePayload, bridgeRequest } from "./bridge.js";
import { startReminderPolling } from "./reminders.js";

const projectId = process.env.PROJECT_ID?.trim();
const projectSecret = process.env.PROJECT_SECRET?.trim();
const bridgeSecret = process.env.MESSAGING_BRIDGE_SECRET?.trim();
const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

if (!projectId || !projectSecret) {
  console.error("Set PROJECT_ID and PROJECT_SECRET in messaging/.env before starting.");
  process.exit(1);
}

if (!bridgeSecret) {
  console.error("Set MESSAGING_BRIDGE_SECRET in messaging/.env and the matching backend setting.");
  process.exit(1);
}

console.log("Connecting to Photon Spectrum...");
const app = await Spectrum({
  projectId,
  projectSecret,
  providers: [imessage.config()],
});

console.log("Winnie listener started. Text help, whoami, or tasks from an allowed phone.");

startReminderPolling(backendUrl, bridgeSecret, async (recipient, text) => {
  const im = imessage(app);
  const user = await im.user(recipient);
  const dm = await im.space.create(user);
  if (dm.type !== "dm") throw new Error("Reminder target is not a direct conversation.");
  const sent = await dm.send(text);
  if (!sent?.id || ("isSent" in sent && sent.isSent === false) ||
      ("sendErrorCode" in sent && sent.sendErrorCode)) {
    throw new Error("Photon did not confirm the reminder send.");
  }
  return sent.id;
});

// Reply within the incoming conversation. Do not log phone numbers or text bodies.
for await (const [space, message] of app.messages) {
  const payload = bridgePayload(message, "type" in space ? space.type : undefined);
  if (payload) {
    let stage = "backend request";
    let httpStatus: number | undefined;
    try {
      const response = await fetch(
        `${backendUrl}/api/messages`,
        {
          ...bridgeRequest(payload, bridgeSecret),
          signal: AbortSignal.timeout(30_000),
        }
      );
      httpStatus = response.status;
      if (!response.ok) {
        throw new Error("Backend rejected the request.");
      }

      //Read Python's reply from the response body.
      const data = await response.json();
      if (typeof data.reply !== "string") {
        throw new Error("Backend did not return a reply string.");
      }

      //Send that reply back to the original conversation via Photon
      stage = "Photon reply";
      await space.send(data.reply);
    } catch {
      // Keep metadata useful without printing phone numbers, messages or credentials.
      console.error("Could not process the message.", { stage, httpStatus });
    }
  }
}


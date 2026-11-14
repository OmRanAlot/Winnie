import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const projectId = process.env.PROJECT_ID?.trim();
const projectSecret = process.env.PROJECT_SECRET?.trim();

if (!projectId || !projectSecret) {
  console.error("Set PROJECT_ID and PROJECT_SECRET in messaging/.env before starting.");
  process.exit(1);
}

console.log("Connecting to Photon Spectrum...");
const app = await Spectrum({
  projectId,
  projectSecret,
  providers: [imessage.config()],
});

console.log("Echo listener started. Text your Photon line from an allowed phone.");

// Reply within the incoming conversation. Do not log phone numbers or text bodies.
for await (const [space, message] of app.messages) {
  if (message.content.type === "text") {
    try {
      await space.send(`echo: ${message.content.text}`);
      console.log("Echo reply sent.");
    } catch {
      console.error("Echo reply failed. Check the Photon connection and project settings.");
    }
  }
}

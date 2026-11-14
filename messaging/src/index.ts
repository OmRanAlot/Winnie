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
      const response = await fetch(
        "http://localhost:8000/api/messages",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            text: message.content.text,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(`Backend request failed: ${response.status}`)
      }

      //Read Python's reply from the response body.
      const data = await response.json();

      //Send that reply back to the original conversation via Photon
      await space.send(data.reply);
    } catch { console.error("Could not process the message.") }
  }
}


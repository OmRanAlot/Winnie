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
      const text = message.content.text.trim().toLowerCase();

      if (text === "help") {
        await space.send("Hi! I'm Winnie, the WiCS Project Manager. I help coordinate WiCS tasks and ensure nothing is falling behind. For now, try texting ping.");
      }

      else if (text === "ping") {
        await space.send("pong 🐼🏓");
      }

      else {
        await space.send('Hey! I have not been completely developed yet. Text "help" to see what I can do and my intended purpose. ')
      }
      console.log("Message received. Reply sent.");
    } catch {
      console.error("Echo reply failed. Check the Photon connection and project settings.");
    }
  }
}

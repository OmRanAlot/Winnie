/**
 * Local Photon test CLI. Uses a phone/email you pass on the command line —
 * never reads roster numbers from Supabase.
 *
 *   npm run test:photon -- send --to +15551234567 --text "hello"
 *   npm run test:photon -- listen --from +15551234567
 *   npm run test:photon -- chat --to +15551234567
 *   npm run test:photon -- chat --to +15551234567 --bridge
 *
 * Requires PROJECT_ID + PROJECT_SECRET (messaging/.env) or WINNIE_PHOTON_* fallbacks.
 * Your number must be added under Users in the Photon dashboard (shared-line allowlist).
 */
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { bridgePayload, bridgeRequest } from "../src/bridge.js";

type Args = {
  command: "send" | "listen" | "chat" | "help";
  to?: string;
  from?: string;
  text?: string;
  bridge: boolean;
  backendUrl: string;
};

function usage(): string {
  return [
    "Photon local test (pass YOUR number; nothing is loaded from the member store)",
    "",
    "  send   --to <E.164|email> --text <message>     Bot texts your phone",
    "  listen --from <E.164|email>                    Print inbound from that handle",
    "  chat   --to <E.164|email> [--bridge]           Interactive send + listen",
    "",
    "  --bridge   On inbound DM, POST /api/messages and send Winnie's reply",
    "             (needs local backend + MESSAGING_BRIDGE_SECRET)",
    "",
    "Add your number in https://app.photon.codes → project → Users first.",
  ].join("\n");
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    command: "help",
    bridge: false,
    backendUrl: (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, ""),
  };
  const positionals: string[] = [];
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--to") args.to = argv[++i];
    else if (token === "--from") args.from = argv[++i];
    else if (token === "--text" || token === "-m") args.text = argv[++i];
    else if (token === "--bridge") args.bridge = true;
    else if (token === "--backend") {
      const value = argv[++i];
      if (!value || value.startsWith("-")) throw new Error("--backend requires a URL, e.g. --backend http://127.0.0.1:8000");
      args.backendUrl = value.replace(/\/$/, "");
    }
    else if (token === "--help" || token === "-h") args.command = "help";
    else if (token.startsWith("-")) throw new Error(`Unknown flag: ${token}`);
    else positionals.push(token);
  }
  if (positionals[0] === "send" || positionals[0] === "listen" || positionals[0] === "chat" || positionals[0] === "help") {
    args.command = positionals[0];
  } else if (positionals[0]) {
    throw new Error(`Unknown command: ${positionals[0]}`);
  }
  // Allow: send --to +1... hello world
  if (args.command === "send" && !args.text && positionals.length > 1) {
    args.text = positionals.slice(1).join(" ");
  }
  return args;
}

/** Accept E.164 phones or iMessage email handles. Never invent a number. */
function normalizeHandle(raw: string | undefined, label: string): string {
  if (!raw?.trim()) throw new Error(`Missing ${label}. Example: --to +15551234567`);
  const value = raw.trim();
  if (value.includes("@")) return value.toLowerCase();
  if (!/^\+[1-9]\d{7,14}$/.test(value)) {
    throw new Error(`${label} must be E.164 (+15551234567) or an iMessage email handle.`);
  }
  return value;
}

function credentials() {
  const projectId = process.env.PROJECT_ID?.trim() || process.env.WINNIE_PHOTON_PROJECT_ID?.trim();
  const projectSecret =
    process.env.PROJECT_SECRET?.trim() || process.env.WINNIE_PHOTON_PROJECT_SECRET?.trim();
  if (!projectId || !projectSecret) {
    throw new Error(
      "Set PROJECT_ID and PROJECT_SECRET in messaging/.env (or WINNIE_PHOTON_PROJECT_ID / WINNIE_PHOTON_PROJECT_SECRET).",
    );
  }
  return { projectId, projectSecret };
}

async function connect() {
  const { projectId, projectSecret } = credentials();
  console.log("Connecting to Photon Spectrum...");
  return Spectrum({
    projectId,
    projectSecret,
    providers: [imessage.config()],
  });
}

function senderMatches(message: { sender?: { id?: string } }, handle: string): boolean {
  const id = message.sender?.id?.trim();
  if (!id) return false;
  if (handle.includes("@")) return id.toLowerCase() === handle;
  // Photon may return the same digits with or without punctuation.
  const digits = (s: string) => s.replace(/\D/g, "");
  return id === handle || digits(id) === digits(handle);
}

async function sendOutbound(app: Awaited<ReturnType<typeof connect>>, to: string, text: string) {
  const im = imessage(app);
  const user = await im.user(to);
  const dm = await im.space.create(user);
  if (dm.type !== "dm") throw new Error("Expected a direct conversation.");
  const sent = await dm.send(text);
  if (!sent?.id || ("isSent" in sent && sent.isSent === false) || ("sendErrorCode" in sent && sent.sendErrorCode)) {
    throw new Error("Photon did not confirm the send. Is your number allowlisted under Users?");
  }
  console.log(`Sent (${sent.id}).`);
}

async function bridgeReply(
  message: Parameters<typeof bridgePayload>[0],
  spaceType: unknown,
  spaceId: string | undefined,
  backendUrl: string,
): Promise<string | null> {
  const secret = process.env.MESSAGING_BRIDGE_SECRET?.trim() || process.env.WINNIE_MESSAGING_BRIDGE_SECRET?.trim();
  if (!secret) throw new Error("Set MESSAGING_BRIDGE_SECRET (same value as WINNIE_MESSAGING_BRIDGE_SECRET) for --bridge.");
  const payload = bridgePayload(message, spaceType, spaceId);
  if (!payload) return null;
  const response = await fetch(`${backendUrl}/api/messages`, {
    ...bridgeRequest(payload, secret),
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) {
    throw new Error(`Backend rejected the message (HTTP ${response.status}). Is the API running locally?`);
  }
  const data = (await response.json()) as { reply?: unknown };
  if (data.reply === null) {
    console.warn("Backend returned reply=null (WINNIE_PHOTON_ENABLED webhook mode?). Set it false for local testing.");
    return null;
  }
  if (typeof data.reply !== "string") throw new Error("Backend did not return a reply string.");
  return data.reply;
}

async function listenLoop(
  app: Awaited<ReturnType<typeof connect>>,
  from: string,
  options: { bridge: boolean; backendUrl: string; once?: boolean },
) {
  console.log(`Listening for inbound DMs from your handle. Ctrl+C to stop.`);
  for await (const [space, message] of app.messages) {
    if (!senderMatches(message, from)) continue;
    const preview =
      message.content.type === "text" && typeof message.content.text === "string"
        ? message.content.text
        : `[${message.content.type}]`;
    console.log(`\n← ${preview}`);

    if (options.bridge && "type" in space) {
      try {
        const reply = await bridgeReply(message, space.type, space.id, options.backendUrl);
        if (reply) {
          await space.send(reply);
          console.log(`→ ${reply}`);
        }
      } catch (err) {
        console.error("Bridge failed:", err instanceof Error ? err.message : err);
      }
    }
    if (options.once) break;
  }
}

async function chatLoop(app: Awaited<ReturnType<typeof connect>>, to: string, bridge: boolean, backendUrl: string) {
  const im = imessage(app);
  const user = await im.user(to);
  const dm = await im.space.create(user);
  if (dm.type !== "dm") throw new Error("Expected a direct conversation.");

  console.log("Chat mode. Type a message and Enter to send from the bot.");
  console.log("Inbound texts from your phone appear below. /quit to exit.");
  if (bridge) console.log(`Bridging inbound to ${backendUrl}/api/messages`);

  const rl = createInterface({ input, output });
  let quitting = false;

  // One consumer of app.messages (Spectrum shares a single subscription).
  const inbound = (async () => {
    for await (const [space, message] of app.messages) {
      if (quitting) break;
      if (!senderMatches(message, to)) continue;
      const preview =
        message.content.type === "text" && typeof message.content.text === "string"
          ? message.content.text
          : `[${message.content.type}]`;
      console.log(`\n← ${preview}`);
      if (bridge && "type" in space) {
        try {
          const reply = await bridgeReply(message, space.type, space.id, backendUrl);
          if (reply) {
            await space.send(reply);
            console.log(`→ ${reply}`);
          }
        } catch (err) {
          console.error("Bridge failed:", err instanceof Error ? err.message : err);
        }
      }
    }
  })();

  try {
    while (!quitting) {
      const line = (await rl.question("you> ")).trim();
      if (!line) continue;
      if (line === "/quit" || line === "/exit") {
        quitting = true;
        break;
      }
      const sent = await dm.send(line);
      if (!sent?.id || ("isSent" in sent && sent.isSent === false)) {
        console.error("Send was not confirmed.");
        continue;
      }
      console.log(`→ (delivered to your phone)`);
    }
  } finally {
    rl.close();
  }

  // Force-exit: the inbound for-await only wakes on the next Photon event.
  void inbound;
  process.exit(0);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.command === "help") {
    console.log(usage());
    return;
  }

  if (process.env.WINNIE_PHOTON_ENABLED?.toLowerCase() === "true" && args.bridge) {
    console.warn("WINNIE_PHOTON_ENABLED=true — local bridge replies will be null until you set it false.");
  }

  const app = await connect();

  if (args.command === "send") {
    const to = normalizeHandle(args.to, "--to");
    const text = args.text?.trim();
    if (!text) throw new Error('Missing --text. Example: --text "ping"');
    await sendOutbound(app, to, text);
    // Spectrum keeps a WebSocket open; exit explicitly after a one-shot send.
    process.exit(0);
  }

  if (args.command === "listen") {
    const from = normalizeHandle(args.from ?? args.to, "--from");
    await listenLoop(app, from, { bridge: args.bridge, backendUrl: args.backendUrl });
    return;
  }

  if (args.command === "chat") {
    const to = normalizeHandle(args.to ?? args.from, "--to");
    await chatLoop(app, to, args.bridge, args.backendUrl);
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});

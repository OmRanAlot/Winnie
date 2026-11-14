// Build the backend request from Photon metadata, never from claims in message text.
type BridgeMessage = {
  id: string;
  direction: "inbound" | "outbound";
  platform: string;
  sender?: { id: string; kind?: string };
  content: { type: string; text?: unknown };
};

export function bridgePayload(message: BridgeMessage, spaceType: unknown) {
  if (
    message.direction !== "inbound" || message.sender?.kind === "agent" ||
    message.content.type !== "text" || typeof message.content.text !== "string"
  ) {
    return null;
  }
  return {
    text: message.content.text,
    message_id: message.id,
    sender_id: message.sender?.id ?? null,
    platform: message.platform,
    conversation_type: spaceType === "dm" || spaceType === "group" ? spaceType : "unknown",
  };
}

export function bridgeRequest(payload: NonNullable<ReturnType<typeof bridgePayload>>, secret: string) {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Winnie-Bridge-Secret": secret,
    },
    body: JSON.stringify(payload),
  };
}

// Poll a durable backend outbox. Only the backend supplies recipients and text.
type Delivery = {
  id: string;
  claim_token: string;
  transport: "photon";
  recipient: string;
  text: string;
};
type Outcome = {
  outcome: "sent" | "uncertain";
  provider_message_id?: string;
};
export type ReminderApi = {
  next(scan: boolean): Promise<{ delivery: Delivery | null; mock_processed?: number }>;
  result(delivery: Delivery, outcome: Outcome): Promise<void>;
};

export async function reminderCycle(
  api: ReminderApi,
  send: (recipient: string, text: string) => Promise<string>,
  outcomes = new Map<string, Outcome>(),
) {
  const counts = { provider_accepted: 0, uncertain: 0, ack_failed: 0, mock_processed: 0 };
  for (let index = 0; index < 20; index++) {
    const response = await api.next(index === 0);
    counts.mock_processed += response.mock_processed ?? 0;
    const delivery = response.delivery;
    if (!delivery) break;
    if (
      delivery.transport !== "photon" || !delivery.id || !delivery.claim_token ||
      typeof delivery.recipient !== "string" || !delivery.recipient ||
      typeof delivery.text !== "string" || !delivery.text || delivery.text.length > 2000
    ) {
      throw new Error("Invalid reminder delivery.");
    }
    const key = `${delivery.id}:${delivery.claim_token}`;
    let outcome = outcomes.get(key);
    if (!outcome) {
      try {
        const providerId = await send(delivery.recipient, delivery.text);
        if (!providerId) throw new Error("Provider did not confirm acceptance.");
        outcome = { outcome: "sent", provider_message_id: providerId };
        counts.provider_accepted++;
      } catch {
        // A throw may happen after Photon accepted the send. Never retry the send.
        outcome = { outcome: "uncertain" };
        counts.uncertain++;
      }
      outcomes.set(key, outcome);
      if (outcomes.size > 2000) outcomes.delete(outcomes.keys().next().value!);
    }
    let acknowledged = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await api.result(delivery, outcome);
        acknowledged = true;
        break;
      } catch {
        // Retrying an acknowledgement is safe; this never repeats the Photon send.
      }
    }
    if (!acknowledged) counts.ack_failed++;
  }
  return counts;
}

export function startReminderPolling(
  backendUrl: string,
  secret: string,
  send: (recipient: string, text: string) => Promise<string>,
) {
  if (process.env.REMINDER_POLL_ENABLED !== "true") return;
  const outcomes = new Map<string, Outcome>();
  async function post(path: string, body: object) {
    const response = await fetch(`${backendUrl}/api/internal/reminders/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Winnie-Bridge-Secret": secret },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) throw new Error(`Reminder API HTTP ${response.status}`);
    return response.json();
  }
  const api: ReminderApi = {
    next: scan => post("next", { scan }),
    result: async (delivery, outcome) => {
      await post("result", { delivery_id: delivery.id, claim_token: delivery.claim_token, ...outcome });
    },
  };
  async function boundedSend(recipient: string, text: string) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        send(recipient, text),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("Provider send deadline exceeded.")), 20_000);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }
  async function poll() {
    try {
      const counts = await reminderCycle(api, boundedSend, outcomes);
      if (Object.values(counts).some(value => value > 0)) console.log("Reminder cycle:", counts);
    } catch {
      console.error("Reminder cycle failed. Check backend status and the reminder outbox.");
    }
    setTimeout(() => { void poll(); }, 60_000);
  }
  console.log("Reminder polling enabled; the backend controls mock or Photon delivery.");
  void poll();
}

// The backend authorizes a specific action once. Uncertain sends/group creation are never retried.
export type HelpDelivery = {
  id: string; claim_token: string; kind: "dm" | "group";
  recipient: string; second_recipient?: string; text: string;
};
type Result = { outcome: "sent" | "uncertain"; provider_id?: string };
type Api = {
  next(): Promise<{ delivery: HelpDelivery | null }>;
  result(delivery: HelpDelivery, result: Result): Promise<unknown>;
};

export async function helpCycle(api: Api, execute: (delivery: HelpDelivery) => Promise<string>,
                                outcomes = new Map<string, Result>()) {
  for (let i = 0; i < 20; i++) {
    const { delivery } = await api.next();
    if (!delivery) break;
    if (!delivery.id || !delivery.claim_token || !delivery.recipient || !delivery.text ||
        delivery.text.length > 2000 || !["dm", "group"].includes(delivery.kind) ||
        (delivery.kind === "group" && (!delivery.second_recipient || delivery.second_recipient === delivery.recipient))) {
      throw new Error("Invalid handoff delivery");
    }
    const key = `${delivery.id}:${delivery.claim_token}`;
    let result = outcomes.get(key);
    if (!result) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const id = await Promise.race([execute(delivery), new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("Handoff action deadline exceeded")), 20000);
        })]);
        if (!id) throw new Error("Provider receipt missing");
        result = { outcome: "sent", provider_id: id };
      } catch {
        result = { outcome: "uncertain" };
      } finally { clearTimeout(timer); }
      outcomes.set(key, result);
      if (outcomes.size > 2000) outcomes.delete(outcomes.keys().next().value!);
    }
    for (let attempt = 0; attempt < 3; attempt++) {
      try { await api.result(delivery, result); break; } catch { /* retry receipt only */ }
    }
  }
}

export function startHelpPolling(backendUrl: string, secret: string, execute: (delivery: HelpDelivery) => Promise<string>) {
  if (process.env.HELP_POLL_ENABLED !== "true") return;
  const outcomes = new Map<string, Result>();
  async function post(path: string, body: object) {
    const response = await fetch(`${backendUrl}/api/internal/help/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Winnie-Bridge-Secret": secret },
      body: JSON.stringify(body), signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error(`Help API HTTP ${response.status}`);
    return response.json();
  }
  const api: Api = {
    next: () => post("next", {}),
    result: (delivery, result) => post("result", { delivery_id: delivery.id, claim_token: delivery.claim_token, ...result }),
  };
  async function poll() {
    try { await helpCycle(api, execute, outcomes); }
    catch { console.error("Handoff notification cycle failed; check the backend and outbox."); }
    setTimeout(() => { void poll(); }, 60000);
  }
  void poll();
}

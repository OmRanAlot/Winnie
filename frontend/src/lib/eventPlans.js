const STORAGE_KEY = "winnie.eventPlans.v1";

function readPlans() {
  const raw = globalThis.localStorage.getItem(STORAGE_KEY);
  if (!raw) return [];

  let plans;
  try {
    plans = JSON.parse(raw);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("Saved event plans could not be read because browser storage is invalid.");
    }
    throw error;
  }
  if (!Array.isArray(plans) || plans.some((plan) =>
    !plan || typeof plan.id !== "string" || typeof plan.event_name !== "string" ||
    typeof plan.event_date !== "string" || typeof plan.plan_text !== "string" ||
    typeof plan.updated_at !== "string"
  )) {
    throw new Error("Saved event plans have an invalid format.");
  }
  return plans;
}

function writePlans(plans) {
  globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(plans));
}

export async function getEventPlans() {
  return readPlans().sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

export async function getEventPlan(id) {
  const plan = readPlans().find((item) => item.id === id);
  if (!plan) throw new Error("Saved event plan not found in this browser.");
  return plan;
}

export async function createEventPlan(plan) {
  const now = new Date().toISOString();
  const saved = { ...plan, id: globalThis.crypto.randomUUID(), created_at: now, updated_at: now };
  writePlans([saved, ...readPlans()]);
  return saved;
}

export async function updateEventPlan(id, changes) {
  const plans = readPlans();
  const index = plans.findIndex((plan) => plan.id === id);
  if (index < 0) throw new Error("Saved event plan not found in this browser.");

  const saved = { ...plans[index], ...changes, updated_at: new Date().toISOString() };
  plans[index] = saved;
  writePlans(plans);
  return saved;
}

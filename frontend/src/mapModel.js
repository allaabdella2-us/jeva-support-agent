// Architecture map: layout + a step plan derived from the backend trace.
// Values prefixed with "!" are drawn as warnings (orange).

const L = 58, C = 170, R = 282;
export const E = "…";
export const VIEW_H = 1286;

// id: [centerX, top, width, height, title, owner, placeholder rows]
// owner: c = customer, p = Python, j = Jev, g = Claude
export const NODES = {
  customer: [C, 8, 150, 44, "Customer ticket", "c", [E]],
  det: [C, 82, 150, 44, "Deterministic code", "p", [["status", E]]],
  closed: [100, 156, 100, 44, "Closed?", "p", [E]],
  ctx: [244, 156, 116, 44, "Build context", "p", [E]],
  noaction: [100, 230, 100, 44, "No action", "p", [E]],
  memory: [244, 230, 130, 58, "Load memory", "p", [["turns", E], ["past 7 days", E]]],
  jev: [C, 318, 150, 44, "Jev (System One)", "j", [E]],
  choice: [L, 392, 108, 58, "Choice (1)", "j", [["topic", E], ["conf", E]]],
  noul: [C, 392, 108, 114, "Noul (6)", "j",
    [["credentials", E], ["identity", E], ["reward", E], ["refund", E], ["open order", E], ["repeat", E]]],
  score: [R, 392, 108, 58, "Score (1)", "j", [["frustration", E], ["conf", E]]],
  policy: [C, 536, 150, 44, "Python policy", "p", [E]],
  gates: [L, 610, 108, 58, "Confidence gates", "p", [["topic", E], ["spam band", E]]],
  spam: [C, 610, 108, 58, "Spam composite", "p", [["risk", E], ["quarantine", E]]],
  rules: [R, 610, 108, 72, "Business rules", "p", [["priority", E], ["refund ok", E], ["repeat", E]]],
  routing: [C, 712, 150, 44, "Routing", "p", [E]],
  human: [L, 786, 108, 58, "Human review", "p", [["case", E], ["priority", E]]],
  quarantine: [C, 786, 108, 58, "Spam quarantine", "p", [["risk", E], ["action", E]]],
  specialist: [R, 786, 108, 58, "Specialist Claude", "g", [["team", E], ["priority", E]]],
  toolreq: [R, 874, 108, 44, "Tool request", "g", [E]],
  gateway: [R, 948, 108, 44, "Python gateway", "p", [E]],
  order: [L, 1022, 108, 44, "Order status", "p", [E]],
  refund: [C, 1022, 108, 44, "Refund", "p", [E]],
  password: [R, 1022, 108, 44, "Password", "p", [E]],
  result: [C, 1096, 150, 44, "Tool result", "p", [E]],
  gpt: [C, 1170, 150, 44, "Claude", "g", [E]],
  response: [C, 1236, 150, 44, "Customer response", "c", [E]],
};

export const EDGES = [
  ["customer", "det"], ["det", "closed"], ["det", "ctx"], ["closed", "noaction"],
  ["ctx", "memory"], ["memory", "jev"],
  ["jev", "choice"], ["jev", "noul"], ["jev", "score"],
  ["choice", "policy"], ["noul", "policy"], ["score", "policy"],
  ["policy", "gates"], ["policy", "spam"], ["policy", "rules"],
  ["gates", "routing"], ["spam", "routing"], ["rules", "routing"],
  ["routing", "human"], ["routing", "quarantine"], ["routing", "specialist"],
  ["specialist", "toolreq"], ["toolreq", "gateway"],
  ["gateway", "order"], ["gateway", "refund"], ["gateway", "password"],
  ["order", "result"], ["refund", "result"], ["password", "result"],
  ["result", "gpt"], ["gpt", "response"],
];

export const OWNER_COLOR = {
  c: "var(--orange)", p: "var(--muted)", j: "var(--teal)", g: "var(--purple)",
};

export function edgePath([a, b]) {
  const [x1, t1, , h1] = NODES[a];
  const [x2, t2] = NODES[b];
  const s = t1 + h1, t = t2, m = (s + t) / 2;
  return `M${x1} ${s} C${x1} ${m} ${x2} ${m} ${x2} ${t}`;
}

const f2 = (n) => (n == null ? E : Number(n).toFixed(2));
const flag = (cond, v) => (cond ? "!" : "") + v;
const TOOL_NODE = { get_order_status: "order", create_refund: "refund", reset_password: "password" };

function niceDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function toolValue(call) {
  const r = call.result || {};
  if (!call.allowed) return ["!blocked"];
  if (call.name === "get_order_status") {
    if (!r.found) return ["!not found"];
    const o = r.order;
    return [o.status === "shipped" ? `${o.carrier}, ${niceDate(o.estimated_delivery)}` : o.status];
  }
  if (call.name === "create_refund") return r.success ? [flag(r.status === "pending_approval", r.refund_id)] : ["!failed"];
  if (call.name === "reset_password") return r.success ? ["link sent"] : ["!failed"];
  return [r.status || "done"];
}

function resultValue(call) {
  const r = call.result || {};
  if (call.name === "get_order_status") return [r.found ? "found: true" : "!found: false"];
  if (r.success === false) return ["!error"];
  return [r.already_submitted ? "already submitted" : r.status || "ok"];
}

// Build the ordered list of animation steps from a trace.
export function buildPlan(trace, senderName) {
  const steps = [];
  const step = (s) => steps.push({ lit: [], edges: [], vals: {}, ...s });
  const t = trace;
  const closed = t.ticket.status_check === "closed";

  step({ lit: [["customer"]], vals: { customer: [senderName || "Customer"] }, caption: "Ticket arrives" });
  step({ edges: [["customer", "det"]], lit: [["det"]], vals: { det: [["status", flag(closed, closed ? "closed" : "open")]] }, caption: "Deterministic checks" });
  step({ edges: [["det", "closed"]], lit: [["closed"]], vals: { closed: [flag(closed, closed ? "yes" : "no")] } });
  if (closed) {
    step({ edges: [["closed", "noaction"]], lit: [["noaction", "end-hold"]], vals: { noaction: ["already closed"] }, caption: "Closed ticket, no action", end: true });
    return steps;
  }
  if (t.route === "unknown_customer") {
    step({ edges: [["det", "ctx"]], lit: [["ctx", "end-hold"]], vals: { ctx: ["!unknown sender"] }, caption: `Unknown sender, case ${t.human_case?.case_id || ""}`, end: true });
    return steps;
  }
  const openOrders = t.customer?.open_orders?.length ?? 0;
  step({ edges: [["det", "ctx"]], lit: [["ctx"]], vals: { ctx: [`${openOrders} open order${openOrders === 1 ? "" : "s"}`] }, caption: "Build focused context" });
  const mem = t.memory || {};
  const contacts = mem.history?.contacts_last_7_days ?? 0;
  step({ edges: [["ctx", "memory"]], lit: [["memory"]], vals: { memory: [["turns", String(mem.turns_remembered ?? 0)], ["past 7 days", flag(contacts >= (t.policy?.thresholds?.repeat_contact_min ?? 2), String(contacts))]] }, caption: "Load conversation and history" });

  const j = t.jev || {};
  const th = t.policy?.thresholds || {};
  step({ edges: [["memory", "jev"]], lit: [["jev"]], vals: { jev: ["reading…"] }, caption: "Jev answers 8 semantic questions" });
  step({ edges: [["jev", "choice"]], lit: [["choice"]], vals: { choice: [["topic", j.topic?.choice ?? E], ["conf", flag(j.topic?.confidence < th.topic_min_confidence, f2(j.topic?.confidence))]] } });
  const risky = (k) => flag((j[k]?.noul ?? 0) >= 0.5, f2(j[k]?.noul));
  const act = (k) => flag(false, f2(j[k]?.noul));
  step({ edges: [["jev", "noul"]], lit: [["noul"]], vals: { noul: [
    ["credentials", risky("requests_credentials")], ["identity", risky("sender_identity_mismatch")],
    ["reward", risky("unexpected_reward")], ["refund", act("refund_requested")],
    ["open order", act("mentions_open_order")], ["repeat", flag((j.repeat_contact?.noul ?? 0) >= th.noul_action, f2(j.repeat_contact?.noul))],
  ] } });
  step({ edges: [["jev", "score"]], lit: [["score"]], vals: { score: [["frustration", flag(j.frustration?.score >= th.high_frustration_score, f2(j.frustration?.score))], ["conf", f2(j.frustration?.confidence)]], jev: ["8 answers"] } });

  const p = t.policy || {};
  const outcome = p.human_review ? "!hold for review" : p.quarantine ? "!quarantine" : "all clear";
  step({ edges: [["choice", "policy"], ["noul", "policy"], ["score", "policy"]], lit: [["policy"]], vals: { policy: [outcome] }, caption: "Python composes the rules" });
  step({
    edges: [["policy", "gates"], ["policy", "spam"], ["policy", "rules"]],
    lit: [["gates"], ["spam"], ["rules"]],
    vals: {
      gates: [["topic", p.topic_ok ? "pass" : "!too low"], ["spam band", p.spam_uncertain ? "!ambiguous" : "pass"]],
      spam: [["risk", flag(p.spam_risk >= th.spam_low, f2(p.spam_risk))], ["quarantine", p.quarantine ? "!yes" : "no"]],
      rules: [["priority", flag(p.priority === "high", p.priority || E)], ["refund ok", p.refund_ok ? "yes" : "no"], ["repeat", flag(p.repeat_contact, p.repeat_contact ? "yes" : "no")]],
    },
  });
  step({ edges: [["gates", "routing"], ["spam", "routing"], ["rules", "routing"]], lit: [["routing"]], vals: { routing: [t.route === "specialist" ? t.specialist : t.route] }, caption: "Routing" });

  if (t.route === "human_review") {
    step({ edges: [["routing", "human"]], lit: [["human", "end-hold"]], vals: { human: [["case", t.human_case?.case_id ?? E], ["priority", t.human_case?.priority ?? E]] }, caption: "Sent to a person for review", end: true });
    return steps;
  }
  if (t.route === "spam_quarantine") {
    step({ edges: [["routing", "quarantine"]], lit: [["quarantine", "end-warn"]], vals: { quarantine: [["risk", f2(p.spam_risk)], ["action", "quarantined"]] }, caption: "Quarantined as likely phishing", end: true });
    return steps;
  }
  step({ edges: [["routing", "specialist"]], lit: [["specialist"]], vals: { specialist: [["team", j.topic?.choice ?? E], ["priority", flag(t.priority === "high", t.priority)]] }, caption: "Specialist LLM takes the ticket" });

  const calls = t.tool_calls || [];
  if (calls.length) {
    step({ edges: [["specialist", "toolreq"]], lit: [["toolreq"]], vals: { toolreq: [calls[0].name] }, caption: "The LLM asks, the Python gateway decides" });
    step({ edges: [["toolreq", "gateway"]], lit: [["gateway"]], vals: { gateway: [calls.every((c) => c.allowed) ? "allowed" : "!blocked"] } });
    let reached = false;
    for (const c of calls) {
      const node = TOOL_NODE[c.name];
      if (!node) continue;
      step({ edges: [["gateway", node]], lit: [[node, c.allowed ? "on" : "blocked"]], vals: { [node]: toolValue(c) } });
      if (c.allowed) {
        step({ edges: [[node, "result"]], lit: [["result"]], vals: { result: resultValue(c) } });
        reached = true;
      }
    }
    if (!reached) step({ lit: [["result"]], vals: { result: resultValue(calls[0]) } });
    step({ edges: [["result", "gpt"]], lit: [["gpt"]], vals: { gpt: ["writing…"] }, caption: "The LLM writes the reply" });
  } else {
    step({ edges: [["specialist", "toolreq"]], lit: [["toolreq"]], vals: { toolreq: ["none needed"] }, caption: "No tool needed" });
    step({ lit: [["gpt"]], vals: { gpt: ["writing…"] }, caption: "The LLM writes the reply" });
  }
  const words = (t.reply || "").split(/\s+/).filter(Boolean).length;
  step({ edges: [["gpt", "response"]], lit: [["response", "end-good"]], vals: { gpt: [`${words} words`], response: ["delivered"] }, caption: "Reply delivered", end: true });
  return steps;
}

// Fold steps[0..upto] into the current map state.
export function stateAt(steps, upto) {
  const nodes = {}, edges = new Set(), vals = {};
  let caption = "Send a message to trace its path";
  let now = null;
  steps.slice(0, upto + 1).forEach((s) => {
    s.edges.forEach(([a, b]) => edges.add(`${a}-${b}`));
    s.lit.forEach(([id, cls = "on"]) => { nodes[id] = cls; now = id; });
    Object.assign(vals, s.vals);
    if (s.caption) caption = s.caption;
  });
  const done = upto >= steps.length - 1 && steps.length > 0;
  return { nodes, edges, vals, caption, now: done ? null : now, done };
}

// ============================================================
// IN-BROWSER DEMO BACKEND
// A JavaScript port of support_db.py + support_agent_claude.py +
// mock_models.py, so the React app runs with mock data and no server.
// Same thresholds, same policy, same tool gateway, same memory rules.
// ============================================================

// ---------- thresholds (mirrors the Python) ----------
const T = {
  TOPIC_MIN_CONFIDENCE: 0.75, SPAM_LOW: 0.4, SPAM_HIGH: 0.6, NOUL_ACTION: 0.7,
  HIGH_FRUSTRATION_SCORE: 1.5, HIGH_FRUSTRATION_CONFIDENCE: 0.7,
  REFUND_AUTO_APPROVE_LIMIT_CENTS: 10000, PASSWORD_RESET_TTL_MINUTES: 30,
  MEMORY_MAX_TURNS: 10, HISTORY_WINDOW_DAYS: 30, HISTORY_MAX_TICKETS: 5, REPEAT_CONTACT_MIN: 2,
};

// ---------- time helpers: seed dates are relative to "now" ----------
const DAY = 86400000;
const iso = (d) => new Date(d).toISOString().replace(/\.\d{3}Z$/, "Z");
const nowIso = () => iso(Date.now());
const ago = (days, hours = 0) => iso(Date.now() - days * DAY - hours * 3600000);
const dateOnly = (offsetDays) => iso(Date.now() + offsetDays * DAY).slice(0, 10);

// ============================================================
// SEED DATA
// ============================================================
function seed() {
  const customers = [
    { id: "CUST-1001", name: "Jane Smith", email: "jane@example.com", plan: "premium" },
    { id: "CUST-1002", name: "Marcus Lee", email: "marcus@example.com", plan: "basic" },
    { id: "CUST-1003", name: "Priya Patel", email: "priya@example.com", plan: "plus" },
    { id: "CUST-1004", name: "Diego Alvarez", email: "diego@example.com", plan: "premium" },
    { id: "CUST-1005", name: "Hannah Kim", email: "hannah@example.com", plan: "basic" },
  ];
  const o = (id, customer_id, status, carrier, tracking_number, estimated_delivery, delivered_at, total_cents, item_summary, created_at) =>
    ({ id, customer_id, status, carrier, tracking_number, estimated_delivery, delivered_at, total_cents, item_summary, created_at });
  const orders = [
    o("A-104", "CUST-1001", "shipped", "UPS", "1Z999AA", dateOnly(2), null, 4250, "Blood pressure monitor", ago(4)),
    o("A-101", "CUST-1001", "delivered", "FedEx", "7712 3456 01", null, dateOnly(-13), 6499, "Diabetic test strips (100 count)", ago(17)),
    o("A-095", "CUST-1001", "delivered", "USPS", "9400 1112 22", null, dateOnly(-54), 1899, "Compression socks (2 pairs)", ago(59)),
    o("A-110", "CUST-1002", "processing", null, null, dateOnly(6), null, 3100, "Digital thermometer", ago(1)),
    o("A-107", "CUST-1002", "delivered", "UPS", "1Z888BB", null, dateOnly(-7), 2275, "First aid kit", ago(11)),
    o("A-112", "CUST-1003", "shipped", "FedEx", "7712 9988 44", dateOnly(4), null, 8900, "Nebulizer and tubing", ago(2)),
    o("A-098", "CUST-1003", "returned", "UPS", "1Z777CC", null, dateOnly(-36), 5400, "Knee brace", ago(41)),
    o("A-115", "CUST-1004", "shipped", "USPS", "9400 5566 77", dateOnly(1), null, 2999, "Pill organizer and refills", ago(3)),
    o("A-103", "CUST-1004", "cancelled", null, null, null, null, 15999, "Mobility walker", ago(15)),
    o("A-116", "CUST-1005", "processing", null, null, dateOnly(8), null, 1250, "Hand sanitizer (6 pack)", ago(0, 3)),
  ];
  const c = (id, customer_id, order_id, amount_cents, status, charged_at) => ({ id, customer_id, order_id, amount_cents, status, charged_at });
  const charges = [
    c("CH-5001", "CUST-1001", "A-104", 4250, "settled", ago(4)),
    c("CH-4990", "CUST-1001", "A-101", 6499, "settled", ago(17)),
    c("CH-4991", "CUST-1001", "A-101", 6499, "settled", ago(17)),   // duplicate charge
    c("CH-4870", "CUST-1001", "A-095", 1899, "settled", ago(59)),
    c("CH-5010", "CUST-1002", "A-110", 3100, "pending", ago(1)),
    c("CH-4995", "CUST-1002", "A-107", 2275, "settled", ago(11)),
    c("CH-5004", "CUST-1003", "A-112", 8900, "settled", ago(2)),
    c("CH-4920", "CUST-1003", "A-098", 5400, "refunded", ago(41)),
    c("CH-5002", "CUST-1004", "A-115", 2999, "settled", ago(3)),
    c("CH-4980", "CUST-1004", "A-103", 15999, "refunded", ago(15)),
  ];
  const refunds = [
    { refund_ref: "REF-89990", customer_id: "CUST-1003", order_id: "A-098", charge_id: "CH-4920", amount_cents: 5400, reason: "Item returned", status: "completed", ticket_id: "TICKET-11870", created_at: ago(35) },
    { refund_ref: "REF-89995", customer_id: "CUST-1004", order_id: "A-103", charge_id: "CH-4980", amount_cents: 15999, reason: "Order cancelled", status: "completed", ticket_id: "TICKET-12011", created_at: ago(15) },
  ];
  const human_cases = [
    { case_ref: "CASE-49990", ticket_id: "TICKET-12002", customer_id: "CUST-1002", reason: "Asked about coverage for a thermometer", priority: "normal", status: "resolved", created_at: ago(22) },
    { case_ref: "CASE-49995", ticket_id: "TICKET-12300", customer_id: "CUST-1001", reason: "Repeat contact about order A-104 with no tracking", priority: "high", status: "queued", created_at: ago(1, 1) },
  ];
  const t = (id, customer_id, status, topic, route, specialist, priority, created_at) =>
    ({ id, customer_id, status, topic, route, specialist, priority, created_at, updated_at: created_at });
  const tickets = [
    t("TICKET-11650", "CUST-1001", "closed", "orders", "specialist", "orders_specialist", "normal", ago(57)),
    t("TICKET-12201", "CUST-1001", "closed", "orders", "specialist", "orders_specialist", "normal", ago(3, 2)),
    t("TICKET-12250", "CUST-1001", "closed", "orders", "specialist", "orders_specialist", "normal", ago(2, 4)),
    t("TICKET-12300", "CUST-1001", "escalated", "orders", "human_review", null, "high", ago(1, 1)),
    t("TICKET-12002", "CUST-1002", "closed", "billing", "human_review", null, "normal", ago(22)),
    t("TICKET-11870", "CUST-1003", "closed", "billing", "specialist", "billing_specialist", "normal", ago(35)),
    t("TICKET-12011", "CUST-1004", "closed", "orders", "specialist", "orders_specialist", "normal", ago(15)),
  ];
  const m = [
    ["TICKET-11650", "customer", "My compression socks arrived today. Thanks!", ago(57)],
    ["TICKET-11650", "agent", "Glad they arrived safely, Jane. Enjoy!", ago(57)],
    ["TICKET-12201", "customer", "Hi, can you tell me when order A-104 will arrive?", ago(3, 2)],
    ["TICKET-12201", "agent", "Thanks for reaching out. Your order is being prepared and will ship soon.", ago(3, 2)],
    ["TICKET-12250", "customer", "Following up on order A-104. I still don't have a tracking number.", ago(2, 4)],
    ["TICKET-12250", "agent", "We're looking into this and will update you shortly.", ago(2, 4)],
    ["TICKET-12300", "customer", "This is the third time I'm asking. Where is order A-104?", ago(1, 1)],
    ["TICKET-12300", "system", "Escalated to a person: case CASE-49995.", ago(1, 1)],
    ["TICKET-12002", "customer", "Is a digital thermometer covered by my plan?", ago(22)],
    ["TICKET-12002", "system", "Escalated to a person: case CASE-49990.", ago(22)],
    ["TICKET-11870", "customer", "I returned the knee brace. Can I get a refund?", ago(35)],
    ["TICKET-11870", "agent", "Your refund REF-89990 has been submitted.", ago(35)],
    ["TICKET-12011", "customer", "Please cancel order A-103 and refund me.", ago(15)],
    ["TICKET-12011", "agent", "Order A-103 is cancelled and refund REF-89995 is on its way.", ago(15)],
  ];
  const messages = m.map(([ticket_id, role, content, created_at], i) => ({ id: i + 1, ticket_id, role, content, created_at }));
  return {
    customers, orders, charges, refunds, human_cases, tickets, messages,
    password_resets: [], tool_audit_log: [],
    seq: { refund: 90000, case: 50000, message: messages.length, audit: 0, reset: 0 },
  };
}

let db = seed();

// ============================================================
// DATA ACCESS (mirrors support_db.py)
// ============================================================
const clone = (x) => JSON.parse(JSON.stringify(x));
const findCustomerByEmail = (email) => db.customers.find((c) => c.email.toLowerCase() === String(email).toLowerCase()) || null;
const getCustomerById = (id) => db.customers.find((c) => c.id === id) || null;
const listOrders = (cid) => db.orders.filter((o) => o.customer_id === cid).sort((a, b) => b.created_at.localeCompare(a.created_at));
function getOrderForCustomer(cid, orderId) {
  const o = db.orders.find((x) => x.id === String(orderId).trim().toUpperCase() && x.customer_id === cid);
  if (!o) return null;
  const { id, status, carrier, tracking_number, estimated_delivery, delivered_at, item_summary } = o;
  return { id, status, carrier, tracking_number, estimated_delivery, delivered_at, item_summary };
}
function findRefundableCharge(cid, orderId) {
  const refunded = new Set(db.refunds.map((r) => r.charge_id));
  return db.charges
    .filter((c) => c.customer_id === cid && c.order_id === orderId && c.status === "settled" && !refunded.has(c.id))
    .sort((a, b) => b.charged_at.localeCompare(a.charged_at) || b.id.localeCompare(a.id))[0] || null;
}
const getRefundForTicket = (tid, orderId) => db.refunds.find((r) => r.ticket_id === tid && r.order_id === orderId) || null;
function insertRefund(r) {
  const row = { refund_ref: `REF-${String(++db.seq.refund).padStart(5, "0")}`, ...r, created_at: nowIso() };
  db.refunds.push(row);
  return row;
}
function insertPasswordReset(cid, sent_to) {
  const row = { id: ++db.seq.reset, customer_id: cid, token_hash: "sha256:••••", sent_to, status: "sent",
    created_at: nowIso(), expires_at: iso(Date.now() + T.PASSWORD_RESET_TTL_MINUTES * 60000) };
  db.password_resets.push(row);
  return row;
}
function insertHumanCase(ticket_id, customer_id, reason, priority) {
  const row = { case_ref: `CASE-${String(++db.seq.case).padStart(5, "0")}`, ticket_id, customer_id, reason, priority, status: "queued", created_at: nowIso() };
  db.human_cases.push(row);
  return row;
}
function logToolCall(ticket_id, customer_id, tool_name, args, allowed, result) {
  db.tool_audit_log.push({ id: ++db.seq.audit, ticket_id, customer_id, tool_name,
    arguments_json: JSON.stringify(args), allowed: allowed ? 1 : 0, result_json: JSON.stringify(result), created_at: nowIso() });
}
// memory
const getTicket = (id) => db.tickets.find((t) => t.id === id) || null;
function ensureTicket(id, customer_id) {
  let t = getTicket(id);
  if (!t) {
    const ts = nowIso();
    t = { id, customer_id, status: "open", topic: null, route: null, specialist: null, priority: null, created_at: ts, updated_at: ts };
    db.tickets.push(t);
  }
  return t;
}
function updateTicket(id, fields) {
  const t = getTicket(id);
  Object.assign(t, fields, { updated_at: nowIso() });
}
function addMessage(ticket_id, role, content) {
  db.messages.push({ id: ++db.seq.message, ticket_id, role, content, created_at: nowIso() });
  const t = getTicket(ticket_id);
  if (t) t.updated_at = nowIso();
}
const getMessages = (tid, limit = 10) =>
  db.messages.filter((m) => m.ticket_id === tid).slice(-limit).map(({ role, content, created_at }) => ({ role, content, created_at }));
const snippet = (s, n = 160) => { if (!s) return null; s = s.split(/\s+/).join(" "); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };
function getCustomerHistory(cid, exclude = "", days = T.HISTORY_WINDOW_DAYS, max = T.HISTORY_MAX_TICKETS) {
  const cutoff = ago(days), week = ago(7);
  const others = db.tickets.filter((t) => t.customer_id === cid && t.id !== exclude);
  const recent = others.filter((t) => t.created_at >= cutoff).sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, max);
  const msgs = (tid) => db.messages.filter((m) => m.ticket_id === tid);
  return {
    window_days: days,
    contacts_last_7_days: others.filter((t) => t.created_at >= week).length,
    recent_tickets: recent.map((t) => ({
      id: t.id, created_at: t.created_at, status: t.status, topic: t.topic,
      customer_said: snippet(msgs(t.id).find((m) => m.role === "customer")?.content),
      outcome: snippet([...msgs(t.id)].reverse().find((m) => m.role !== "customer")?.content),
    })),
    open_cases: db.human_cases.filter((c) => c.customer_id === cid && c.status !== "resolved")
      .map(({ case_ref, ticket_id, reason, priority, created_at }) => ({ case_ref, ticket_id, reason, priority, created_at })),
    recent_refunds: db.refunds.filter((r) => r.customer_id === cid && r.created_at >= cutoff)
      .map(({ refund_ref, order_id, amount_cents, status, created_at }) => ({ refund_ref, order_id, amount_cents, status, created_at })),
  };
}

// ============================================================
// MOCK JEV (mirrors mock_models.simulate_jev)
// ============================================================
const orderIds = (text) => [...String(text || "").matchAll(/\b([A-Za-z])-?(\d{3})\b/g)].map((m) => `${m[1].toUpperCase()}-${m[2]}`);
const hits = (re, text) => (text.match(re) || []).length;
const TOPIC = {
  billing: /refund|charge|bill|invoice|payment|paid|subscription|money back|cost|fee|credit/g,
  orders: /order|deliver|ship|package|track|arriv|return|supplies|sign for|parcel/g,
  account: /log ?in|sign ?in|password|locked|account|profile|portal|permission|access|reset|username/g,
};
function topicOf(message, earlier) {
  const m = message.toLowerCase();
  const ranked = Object.entries(TOPIC).map(([k, re]) => [k, hits(re, m)]).sort((a, b) => b[1] - a[1]);
  const [[best, top], [, second]] = ranked;
  if (top === 0) {
    const prev = Object.entries(TOPIC).map(([k, re]) => [k, hits(re, earlier.toLowerCase())]).sort((a, b) => b[1] - a[1])[0];
    return prev[1] ? [prev[0], 0.82] : ["billing", 0.41];
  }
  if (top === second) return [best, 0.58];
  return [best, Math.min(0.97, 0.8 + 0.05 * (top - second))];
}
function simulateJev(state) {
  const { ticket, customer, conversation } = state;
  const msg = ticket.message, m = msg.toLowerCase();
  const earlier = conversation.filter((t) => t.role === "customer").map((t) => t.content).join(" ");
  const history = customer.history;
  const openIds = new Set(customer.open_orders.map((o) => o.id));
  const [choice, conf] = topicOf(msg, earlier);

  const creds = /(send|give|share|provide|reply with|confirm|enter|tell me|verify).{0,50}(password|security code|api key|secret key|\bpin\b|social security)/.test(m);
  const reward = /congratulations|you('ve| have) (won|been selected)|winner|prize|gift card|claim (it|your)/.test(m);
  const refund = /refund|money back|reimburse|credit (back|me)|charged twice|duplicate charge/.test(m);

  const display = ticket.sender.display_name || "";
  const local = (ticket.sender.email || "").split("@")[0].toLowerCase();
  const nameTokens = (display.match(/[A-Za-z]+/g) || []).map((x) => x.toLowerCase());
  const orgWords = /\b(team|support|rewards?|billing|security|service|bank|admin|official|helpdesk)\b/i;
  const mismatch = orgWords.test(display) && !nameTokens.some((t) => t.length > 2 && local.includes(t)) ? 0.9 : 0.03;

  const idsNow = new Set(orderIds(msg)), idsBefore = new Set(orderIds(earlier));
  const anyIn = (set, other) => [...set].some((x) => other.has(x));
  let openOrder = 0.08;
  if (anyIn(idsNow, openIds)) openOrder = 0.96;
  else if (/\b(it|order|package|parcel|delivery)\b/.test(m) && anyIn(idsBefore, openIds)) openOrder = 0.8;
  else if (/order|package/.test(m) && /where|track|late|arriv/.test(m) && openIds.size) openOrder = 0.74;

  const fr = hits(/frustrat|angry|upset|ridiculous|unacceptable|again|third|three times|nobody|never|worst|cancel my|leave|switch|still/g, m);
  const frustration = Math.min(2, 0.2 + 0.55 * fr + (msg.includes("!!") ? 0.3 : 0));

  let repeat = 0.1;
  const past = history.recent_tickets, cases = history.open_cases;
  const pastText = past.map((t) => t.customer_said || "").join(" ") + " " + cases.map((c) => c.reason).join(" ");
  const idsPast = new Set(orderIds(pastText));
  const unresolved = cases.length > 0 || past.some((t) => t.status !== "closed");
  if (anyIn(new Set([...idsNow, ...idsBefore]), idsPast)) repeat = unresolved ? 0.93 : 0.78;
  else if (/again|still|third|times|follow(ing)? up|already/.test(m) && past.some((t) => t.topic === choice)) repeat = 0.75;

  const r2 = (x) => Math.round(x * 100) / 100;
  return {
    topic: { choice, confidence: r2(conf) },
    requests_credentials: { noul: creds ? 0.93 : 0.03 },
    sender_identity_mismatch: { noul: mismatch },
    unexpected_reward: { noul: reward ? 0.95 : 0.02 },
    refund_requested: { noul: refund ? 0.9 : 0.05 },
    mentions_open_order: { noul: openOrder },
    frustration: { score: r2(frustration), confidence: 0.84 },
    repeat_contact: { noul: repeat },
  };
}

// ============================================================
// POLICY (mirrors the Python)
// ============================================================
const spamRisk = (a) => 0.45 * a.requests_credentials.noul + 0.3 * a.sender_identity_mismatch.noul + 0.25 * a.unexpected_reward.noul;
const needsHuman = (a, s) => (T.SPAM_LOW < s && s < T.SPAM_HIGH) || a.topic.confidence < T.TOPIC_MIN_CONFIDENCE;
const isRepeat = (a, h) => a.repeat_contact.noul >= T.NOUL_ACTION && h.contacts_last_7_days >= T.REPEAT_CONTACT_MIN;
const specialistFor = (a) => ({ billing: "billing_specialist", orders: "orders_specialist", account: "account_specialist" })[a.topic.choice] || "general_support";
const priorityFor = (a, h) =>
  (a.frustration.score >= T.HIGH_FRUSTRATION_SCORE && a.frustration.confidence >= T.HIGH_FRUSTRATION_CONFIDENCE) || isRepeat(a, h) ? "high" : "normal";

// ============================================================
// TOOLS + GATEWAY (mirrors the Python)
// ============================================================
function toolGetOrderStatus(cid, orderId) {
  const order = getOrderForCustomer(cid, orderId);
  return order ? { found: true, order } : { found: false, order: null };
}
function toolCreateRefund(cid, orderId, reason, ticketId) {
  const order = getOrderForCustomer(cid, orderId);
  if (!order) return { success: false, error: "Order not found for this customer." };
  const existing = getRefundForTicket(ticketId, order.id);
  if (existing) return { success: true, already_submitted: true, refund_id: existing.refund_ref, order_id: existing.order_id, amount: existing.amount_cents / 100, status: existing.status };
  const charge = findRefundableCharge(cid, order.id);
  if (!charge) return { success: false, error: "No refundable charge found on this order." };
  const status = charge.amount_cents <= T.REFUND_AUTO_APPROVE_LIMIT_CENTS ? "submitted" : "pending_approval";
  const r = insertRefund({ customer_id: cid, order_id: order.id, charge_id: charge.id, amount_cents: charge.amount_cents, reason, status, ticket_id: ticketId });
  return { success: true, refund_id: r.refund_ref, order_id: r.order_id, amount: r.amount_cents / 100, reason: r.reason, status: r.status };
}
function toolResetPassword(cid) {
  const c = getCustomerById(cid);
  if (!c) return { success: false, error: "Customer not found." };
  const r = insertPasswordReset(cid, c.email);
  const [name, domain] = r.sent_to.split("@");
  return { success: true, action: "password_reset_link_sent", sent_to: `${name[0]}***@${domain}`, expires_in_minutes: T.PASSWORD_RESET_TTL_MINUTES, status: "completed" };
}
function toolCreateHumanCase(ticketId, reason, priority, cid) {
  const c = insertHumanCase(ticketId, cid, reason, ["normal", "high"].includes(priority) ? priority : "normal");
  return { success: true, case_id: c.case_ref, ticket_id: c.ticket_id, reason: c.reason, priority: c.priority, status: c.status };
}
function dispatch(name, args, ctx) {
  const blocked = (error) => ({ success: false, blocked: true, error });
  if (!["get_order_status", "create_refund", "reset_password", "create_human_case"].includes(name)) return blocked("Tool is not allowed.");
  if (name === "get_order_status") return toolGetOrderStatus(ctx.customer_id, args.order_id);
  if (name === "create_refund") {
    if (!ctx.refund_requested) return blocked("Refund request was not detected by the routing layer.");
    return toolCreateRefund(ctx.customer_id, args.order_id, args.reason, ctx.ticket_id);
  }
  if (name === "reset_password") {
    if (ctx.topic !== "account") return blocked("Password reset tool is only available for account requests.");
    return toolResetPassword(ctx.customer_id);
  }
  return toolCreateHumanCase(ctx.ticket_id, args.reason, args.priority || ctx.priority, ctx.customer_id);
}
function executeTool(name, args, ctx, trace) {
  const result = dispatch(name, args, ctx);
  const allowed = !result.blocked;
  logToolCall(ctx.ticket_id, ctx.customer_id, name, args, allowed, result);
  trace.push({ name, arguments: args, allowed, result });
  return result;
}

// ============================================================
// MOCK LLM (mirrors mock_models.MockClaudeClient)
// ============================================================
const niceDate = (d) => (d ? new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }) : "");

function llmDecideTool(spec, ctx, messages) {
  const text = messages[messages.length - 1].content;
  const allUser = messages.filter((m) => m.role === "user").map((m) => m.content).join(" ");
  const ids = orderIds(text).length ? orderIds(text) : orderIds(allUser).slice(-1);
  const orderId = ids[0];
  const low = allUser.toLowerCase();
  if (spec === "orders_specialist" && orderId) return { name: "get_order_status", input: { order_id: orderId } };
  if (spec === "billing_specialist" && orderId && /refund|money back|charged twice|duplicate/.test(low))
    return { name: "create_refund", input: { order_id: orderId, reason: /twice|duplicate|double/.test(low) ? "Duplicate charge" : "Customer requested a refund" } };
  if (spec === "account_specialist" && /log ?in|sign ?in|password|locked|reset|access/.test(text.toLowerCase())) return { name: "reset_password", input: {} };
  if (spec === "general_support") return { name: "create_human_case", input: { reason: "Customer needs help from a person", priority: ctx.priority } };
  return null;
}

function llmBody(spec, results, lastUser) {
  if (!results.length) {
    return {
      orders_specialist: "I'd be glad to help with your order. Could you share the order number? It starts with the letter A, like A-123.",
      billing_specialist: "I can help with that. Which charge or invoice are you asking about, and what's the order number?",
      account_specialist: "happy to help with your account. What would you like to change or check?",
      general_support: "thanks for reaching out. Could you tell me a little more about what you need?",
    }[spec];
  }
  const [name, r] = results[0];
  if (r.blocked || (r.success === false && r.error))
    return "I wasn't able to complete that here, so I'd like a member of our team to take a look. Could you confirm the details and I'll make sure it gets to the right person?";
  if (name === "get_order_status") {
    if (!r.found) return "I couldn't find that order on your account. Could you double-check the number?";
    const o = r.order, item = o.item_summary ? ` (${o.item_summary})` : "";
    if (/\bsign(ature)?\b|sign for/.test(lastUser.toLowerCase()) && o.carrier)
      return `the order details don't say whether a signature is needed. Order ${o.id} is with ${o.carrier} (tracking ${o.tracking_number}), and ${o.carrier}'s tracking page will show any signature requirement.`;
    if (o.status === "shipped") return `order ${o.id}${item} has shipped with ${o.carrier}, tracking number ${o.tracking_number}, and is expected to arrive on ${niceDate(o.estimated_delivery)}. If it hasn't arrived by then, just reply here.`;
    if (o.status === "delivered") return `order ${o.id}${item} was delivered on ${niceDate(o.delivered_at)}.`;
    if (o.status === "processing") return `order ${o.id}${item} is being prepared now, with delivery expected around ${niceDate(o.estimated_delivery)}.`;
    return `order ${o.id}${item} is currently marked as ${o.status}.`;
  }
  if (name === "create_refund") {
    if (r.already_submitted) return `your refund for order ${r.order_id} is already in progress under reference ${r.refund_id}.`;
    if (r.status === "pending_approval") return `I've submitted a refund of $${r.amount.toFixed(2)} for order ${r.order_id} (reference ${r.refund_id}). Because of the amount, a team member will approve it before it's processed.`;
    return `I've submitted a refund of $${r.amount.toFixed(2)} for order ${r.order_id}. Your reference number is ${r.refund_id}, and you'll get an email once it's processed.`;
  }
  if (name === "reset_password") return `I've sent a secure password reset link to ${r.sent_to}. It expires in ${r.expires_in_minutes} minutes. We'll never ask you to share your password or a security code.`;
  if (name === "create_human_case") return `I've passed your message to our support team (case ${r.case_id}), and someone will follow up soon.`;
  return "thanks, that's done.";
}

function buildLlmMessages(conversation, current) {
  const map = { customer: "user", agent: "assistant" };
  const turns = conversation.filter((m) => map[m.role]).map((m) => ({ role: map[m.role], content: m.content }));
  turns.push({ role: "user", content: current });
  const merged = [];
  for (const t of turns) {
    if (merged.length && merged[merged.length - 1].role === t.role) merged[merged.length - 1].content += "\n\n" + t.content;
    else merged.push({ ...t });
  }
  while (merged.length && merged[0].role !== "user") merged.shift();
  return merged;
}

function runAgent(ticket, customer, answers, spec, priority, history, conversation, toolTrace) {
  const ctx = {
    customer_id: customer.id, customer_first_name: customer.name.split(" ")[0], ticket_id: ticket.id,
    topic: answers.topic.choice, priority,
    refund_requested: answers.refund_requested.noul >= T.NOUL_ACTION,
    repeat_contact: isRepeat(answers, history),
  };
  const messages = buildLlmMessages(conversation, ticket.message);
  const call = llmDecideTool(spec, ctx, messages);
  const results = [];
  if (call) results.push([call.name, executeTool(call.name, call.input, ctx, toolTrace)]);
  const followup = messages.some((m) => m.role === "assistant");
  let opener = "";
  if (!followup && ctx.repeat_contact) opener = "I can see you've reached out about this before, and I'm sorry it's taken this long. ";
  else if (!followup && priority === "high") opener = "I'm sorry for the frustration. ";
  let body = llmBody(spec, results, ticket.message);
  if (opener) body = body[0].toUpperCase() + body.slice(1);
  return `Hi ${ctx.customer_first_name}, ${opener}${body}`;
}

// ============================================================
// PIPELINE (mirrors handle_customer_ticket)
// ============================================================
function handleTicket(ticket) {
  const trace = { modes: { jev: "mock", claude: "mock", llm: "mock" }, ticket: { id: ticket.id, status_check: "open" },
    customer: null, memory: null, jev: null, policy: null, route: null, specialist: null, priority: null, tool_calls: [], human_case: null, reply: null };
  const stored = getTicket(ticket.id);
  if (ticket.status === "closed" || stored?.status === "closed") {
    trace.ticket.status_check = "closed"; trace.route = "no_action";
    return { route: "no_action", ticket_id: ticket.id, action: "ticket_already_closed", trace };
  }
  const row = findCustomerByEmail(ticket.sender_email);
  if (!row) {
    ensureTicket(ticket.id, null);
    addMessage(ticket.id, "customer", ticket.message);
    const hc = toolCreateHumanCase(ticket.id, "Sender email does not match a customer", "normal", null);
    updateTicket(ticket.id, { status: "escalated", route: "unknown_customer" });
    addMessage(ticket.id, "system", `Escalated to a person: case ${hc.case_id}.`);
    trace.route = "unknown_customer"; trace.human_case = hc;
    return { route: "unknown_customer", ticket_id: ticket.id, human_case: hc, trace };
  }
  const customer = { ...row, orders: listOrders(row.id) };
  const open = customer.orders.filter((o) => !["delivered", "cancelled", "returned"].includes(o.status));
  trace.customer = { id: customer.id, name: customer.name, plan: customer.plan, open_orders: open.map((o) => o.id) };

  ensureTicket(ticket.id, customer.id);
  const conversation = getMessages(ticket.id, T.MEMORY_MAX_TURNS);
  const history = getCustomerHistory(customer.id, ticket.id);
  addMessage(ticket.id, "customer", ticket.message);
  trace.memory = { turns_remembered: conversation.length, conversation, history };

  const state = {
    ticket: { id: ticket.id, message: ticket.message, sender: { display_name: ticket.sender_name, email: ticket.sender_email } },
    customer: { id: customer.id, name: customer.name, plan: customer.plan, open_orders: customer.orders.filter((o) => o.status !== "delivered"), history },
    conversation,
  };
  const a = simulateJev(state);
  trace.jev = a;

  const spam = spamRisk(a), repeat = isRepeat(a, history), human = needsHuman(a, spam);
  trace.policy = {
    spam_risk: Math.round(spam * 10000) / 10000, topic_ok: a.topic.confidence >= T.TOPIC_MIN_CONFIDENCE,
    spam_uncertain: T.SPAM_LOW < spam && spam < T.SPAM_HIGH, quarantine: !human && spam >= T.SPAM_HIGH, human_review: human,
    repeat_contact: repeat, contacts_last_7_days: history.contacts_last_7_days,
    refund_ok: a.refund_requested.noul >= T.NOUL_ACTION, priority: priorityFor(a, history),
    thresholds: { topic_min_confidence: T.TOPIC_MIN_CONFIDENCE, spam_low: T.SPAM_LOW, spam_high: T.SPAM_HIGH,
      noul_action: T.NOUL_ACTION, high_frustration_score: T.HIGH_FRUSTRATION_SCORE, repeat_contact_min: T.REPEAT_CONTACT_MIN },
  };

  if (human) {
    const hc = toolCreateHumanCase(ticket.id, "Low-confidence classification or ambiguous spam risk", repeat ? "high" : "normal", customer.id);
    updateTicket(ticket.id, { status: "escalated", topic: a.topic.choice, route: "human_review", priority: hc.priority });
    addMessage(ticket.id, "system", `Escalated to a person: case ${hc.case_id}.`);
    Object.assign(trace, { route: "human_review", priority: hc.priority, human_case: hc });
    return { route: "human_review", ticket_id: ticket.id, human_case: hc, trace };
  }
  if (spam >= T.SPAM_HIGH) {
    updateTicket(ticket.id, { status: "quarantined", route: "spam_quarantine" });
    addMessage(ticket.id, "system", "Quarantined as likely spam or phishing.");
    trace.route = "spam_quarantine";
    return { route: "spam_quarantine", ticket_id: ticket.id, action: "quarantined", trace };
  }
  const spec = specialistFor(a), priority = priorityFor(a, history);
  Object.assign(trace, { route: "specialist", specialist: spec, priority });
  const reply = runAgent(ticket, customer, a, spec, priority, history, conversation, trace.tool_calls);
  trace.reply = reply;
  addMessage(ticket.id, "agent", reply);
  updateTicket(ticket.id, { status: "awaiting_customer", topic: a.topic.choice, route: "specialist", specialist: spec, priority });
  return { route: "specialist", ticket_id: ticket.id, specialist: spec, priority, customer_response: reply, trace };
}

// ============================================================
// API (same surface as src/api.js, backed by the in-memory store)
// ============================================================
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const summary = (id) => {
  const t = getTicket(id);
  if (!t) return null;
  const msgs = db.messages.filter((m) => m.ticket_id === id);
  return { ...t, customer_name: getCustomerById(t.customer_id)?.name ?? null, message_count: msgs.length, last_message: msgs[msgs.length - 1]?.content ?? null };
};
const allMessages = (id) => db.messages.filter((m) => m.ticket_id === id).map(({ id, role, content, created_at }) => ({ id, role, content, created_at }));
function nextTicketId() {
  const nums = db.tickets.map((t) => +(/^TICKET-(\d+)$/.exec(t.id)?.[1] || 0));
  return `TICKET-${Math.max(12344, ...nums) + 1}`;
}
async function ok(value, ms = 60) { await wait(ms); return clone(value); }

export const api = {
  health: () => ok({ ok: true, jev_mode: "mock", claude_mode: "mock", llm_provider: "mock", llm_model: "in-browser mock", llm_label: "LLM", demo: true }),
  customers: () => ok(db.customers.map(({ id, name, email, plan }) => ({ id, name, email, plan }))),
  history: (cid) => ok(getCustomerHistory(cid)),
  tickets: (cid) => ok(db.tickets.filter((t) => !cid || t.customer_id === cid)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map((t) => summary(t.id))),
  ticket: (id) => ok({ ticket: summary(id), messages: allMessages(id) }),
  audit: (id) => ok(db.tool_audit_log.filter((r) => r.ticket_id === id)),
  close: async (id) => { updateTicket(id, { status: "closed" }); addMessage(id, "system", "Ticket closed."); return ok({ ticket: summary(id) }); },
  reset: async () => { db = seed(); return ok({ ok: true }); },
  chat: async (body) => {
    await wait(700);   // feel like a network round trip
    const ticket_id = body.ticket_id || nextTicketId();
    const stored = getTicket(ticket_id);
    const result = handleTicket({ id: ticket_id, message: body.message.trim(), sender_name: body.sender_name.trim(),
      sender_email: body.sender_email.trim(), status: stored?.status || "open" });
    const trace = result.trace; delete result.trace;
    return clone({ ticket_id, result, trace, ticket: summary(ticket_id), messages: getTicket(ticket_id) ? allMessages(ticket_id) : [] });
  },
};

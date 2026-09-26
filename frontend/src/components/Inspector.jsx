import { useEffect, useState } from "react";
import PipelineMap from "./PipelineMap.jsx";
import { api } from "../api.js";

const TABS = [
  { id: "map", label: "Map" },
  { id: "jev", label: "Jev & rules" },
  { id: "memory", label: "Memory" },
  { id: "audit", label: "Audit" },
];

const QUESTIONS = {
  topic: ["Choice", "Which team should handle the ticket?"],
  requests_credentials: ["Noul", "Does the message request a sensitive credential?"],
  sender_identity_mismatch: ["Noul", "Does the claimed sender identity conflict with its domain?"],
  unexpected_reward: ["Noul", "Does the message announce an unexpected reward?"],
  refund_requested: ["Noul", "Does the customer explicitly request a refund or credit?"],
  mentions_open_order: ["Noul", "Does the message refer to a supplied open order?"],
  frustration: ["Score", "How frustrated does the customer appear?"],
  repeat_contact: ["Noul", "Is this a repeat contact about the same unresolved issue?"],
};
const RISKY = new Set(["requests_credentials", "sender_identity_mismatch", "unexpected_reward"]);
const f2 = (n) => Number(n).toFixed(2);

function Bar({ value, max = 1, threshold, hot }) {
  return (
    <div className="bar">
      <i className={hot ? "hot" : ""} style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
      {threshold != null && <span className="th" style={{ left: `${(threshold / max) * 100}%` }} />}
    </div>
  );
}

function Empty({ children }) {
  return <p className="panel-empty">{children}</p>;
}

function JevPanel({ trace, llm }) {
  if (!trace?.jev) {
    return <Empty>{trace ? "This ticket stopped before Jev ran." : "Send a message to see Jev's structured answers."}</Empty>;
  }
  const j = trace.jev, p = trace.policy, th = p.thresholds, meta = trace.jev_meta;
  return (
    <div className="panel">
      <h3>Structured output</h3>
      {meta && (
        <p className="panel-meta">
          {trace.modes?.jev === "live" ? <>Answered live by <b>{meta.model}</b></> : <>Answered by the <b>local stand-in</b></>}
          {meta.input_tokens != null && <>, {meta.input_tokens} input tokens</>}
        </p>
      )}
      {Object.entries(QUESTIONS).map(([key, [type, q]]) => {
        const a = j[key];
        if (!a) return null;
        return (
          <div className="qrow" key={key}>
            <span className={`qtype t-${type.toLowerCase()}`}>{type}</span>
            <div>
              <div className="qname">{key}</div>
              <div className="qq">{q}</div>
              {type === "Choice" && (
                <>
                  <div className="opts">
                    {["billing", "orders", "account", "general"].map((o) => (
                      <span key={o} className={`opt${o === a.choice ? " on" : ""}`}>{o}</span>
                    ))}
                  </div>
                  <Bar value={a.confidence} threshold={th.topic_min_confidence} />
                  <div className="barmeta"><span>Confidence <b>{f2(a.confidence)}</b></span><span>Minimum {th.topic_min_confidence}</span></div>
                </>
              )}
              {type === "Noul" && (
                <>
                  <Bar value={a.noul} hot={RISKY.has(key) && a.noul >= 0.5}
                       threshold={["refund_requested", "mentions_open_order", "repeat_contact"].includes(key) ? th.noul_action : null} />
                  <div className="barmeta"><span>noul <b>{f2(a.noul)}</b></span><span>{a.noul >= 0.5 ? "Leans true" : "Leans false"}</span></div>
                </>
              )}
              {type === "Score" && (
                <>
                  <Bar value={a.score} max={2} threshold={th.high_frustration_score} hot={a.score >= th.high_frustration_score} />
                  <div className="barmeta"><span>score <b>{f2(a.score)}</b> of 2</span><span>Confidence <b>{f2(a.confidence)}</b></span></div>
                </>
              )}
            </div>
          </div>
        );
      })}

      <h3>Python policy</h3>
      <div className="formula">
        spam_risk = 0.45 × {f2(j.requests_credentials.noul)} + 0.30 × {f2(j.sender_identity_mismatch.noul)} + 0.25 × {f2(j.unexpected_reward.noul)} = <b className={p.spam_risk >= th.spam_high ? "bad" : ""}>{f2(p.spam_risk)}</b>
      </div>
      <ul className="checks">
        <li className={p.topic_ok ? "" : "fail"}><span>Topic confidence meets {th.topic_min_confidence}</span><b>{p.topic_ok ? "Pass" : "Review"}</b></li>
        <li className={p.spam_uncertain ? "fail" : ""}><span>Spam risk outside {th.spam_low} to {th.spam_high}</span><b>{p.spam_uncertain ? "Review" : "Pass"}</b></li>
        <li className={p.quarantine ? "fail" : ""}><span>Spam risk below {th.spam_high}</span><b>{p.quarantine ? "Quarantine" : "Pass"}</b></li>
        <li className={p.repeat_contact ? "fail" : ""}><span>Repeat contact (Jev ≥ {th.noul_action} and {p.contacts_last_7_days} of {th.repeat_contact_min}+ contacts)</span><b>{p.repeat_contact ? "Yes" : "No"}</b></li>
      </ul>

      <h3>Routing</h3>
      <div className="tiles">
        <div className="tile"><small>Route</small><strong>{trace.route === "specialist" ? trace.specialist.replace("_", " ") : trace.route.replace("_", " ")}</strong></div>
        <div className="tile teal"><small>Priority</small><strong>{trace.priority || p.priority}</strong></div>
      </div>

      {trace.tool_calls.length > 0 && (
        <>
          <h3>Tool gateway</h3>
          {trace.tool_calls.map((c, i) => (
            <div className="toolcall" key={i}>
              <div className="tc-row"><b>{llm} asked</b><code>{c.name}({JSON.stringify(c.arguments)})</code></div>
              <div className="tc-row"><b>Gateway</b><span className={c.allowed ? "ok" : "bad"}>{c.allowed ? "Allowed. Member ID taken from the session." : "Blocked by policy"}</span></div>
              <div className="tc-row"><b>Result</b><pre>{JSON.stringify(c.result, null, 2)}</pre></div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function MemoryPanel({ trace, llm }) {
  const m = trace?.memory;
  if (!m) return <Empty>{trace ? "No memory was loaded for this ticket." : "Send a message to see what Jeva remembered."}</Empty>;
  const h = m.history;
  return (
    <div className="panel">
      <div className="tiles">
        <div className="tile"><small>Turns replayed to {llm}</small><strong>{m.turns_remembered}</strong></div>
        <div className="tile teal"><small>Contacts, last 7 days</small><strong>{h.contacts_last_7_days}</strong></div>
      </div>

      <h3>Earlier in this conversation</h3>
      {m.conversation.length === 0 ? <Empty>This is the first message on the ticket.</Empty> : (
        <ul className="mem-list">
          {m.conversation.map((t, i) => (
            <li key={i}><span className={`role role-${t.role}`}>{t.role}</span>{t.content}</li>
          ))}
        </ul>
      )}

      <h3>Recent tickets ({h.window_days} days)</h3>
      {h.recent_tickets.length === 0 ? <Empty>No other recent tickets.</Empty> : (
        <ul className="mem-list">
          {h.recent_tickets.map((t) => (
            <li key={t.id}>
              <span className="mem-meta">{t.id}, {t.status}, {new Date(t.created_at).toLocaleDateString()}</span>
              <span>“{t.customer_said}”</span>
              {t.outcome && <span className="mem-out">{t.outcome}</span>}
            </li>
          ))}
        </ul>
      )}

      <h3>Open cases</h3>
      {h.open_cases.length === 0 ? <Empty>None.</Empty> : (
        <ul className="mem-list">
          {h.open_cases.map((c) => <li key={c.case_ref}><span className="mem-meta">{c.case_ref}, {c.priority}</span>{c.reason}</li>)}
        </ul>
      )}

      <h3>Recent refunds</h3>
      {h.recent_refunds.length === 0 ? <Empty>None.</Empty> : (
        <ul className="mem-list">
          {h.recent_refunds.map((r) => <li key={r.refund_ref}><span className="mem-meta">{r.refund_ref}, {r.status}</span>Order {r.order_id}, ${(r.amount_cents / 100).toFixed(2)}</li>)}
        </ul>
      )}
    </div>
  );
}

function AuditPanel({ ticketId, refreshKey }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!ticketId) { setRows(null); return; }
    api.audit(ticketId).then(setRows).catch((e) => setError(e.message));
  }, [ticketId, refreshKey]);
  if (!ticketId) return <Empty>Pick or start a ticket to see its tool audit log.</Empty>;
  if (error) return <Empty>Couldn't load the audit log: {error}</Empty>;
  if (!rows) return <Empty>Loading…</Empty>;
  if (rows.length === 0) return <Empty>No tools have run on this ticket.</Empty>;
  return (
    <div className="panel">
      {rows.map((r) => (
        <details className="audit" key={r.id}>
          <summary>
            <span className={r.allowed ? "ok" : "bad"}>{r.allowed ? "Allowed" : "Blocked"}</span>
            <code>{r.tool_name}</code>
            <span className="mem-meta">{new Date(r.created_at).toLocaleTimeString()}</span>
          </summary>
          <pre>{JSON.stringify({ arguments: JSON.parse(r.arguments_json), result: JSON.parse(r.result_json) }, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

export default function Inspector({ trace, senderName, runKey, ticketId, llmLabel = "Claude" }) {
  const [tab, setTab] = useState("map");
  return (
    <section className="card inspector" aria-label="Behind the scenes">
      <div className="band">
        <h2>Behind the scenes</h2>
        <p className="desc">From question to Jev to structured meaning to reply</p>
      </div>
      <div className="tabbar" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" type="button" aria-selected={tab === t.id}
                  className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === "map" && <PipelineMap trace={trace} senderName={senderName} runKey={runKey} llmLabel={llmLabel} />}
        {tab === "jev" && <JevPanel trace={trace} llm={llmLabel} />}
        {tab === "memory" && <MemoryPanel trace={trace} llm={llmLabel} />}
        {tab === "audit" && <AuditPanel ticketId={ticketId} refreshKey={runKey} />}
      </div>
    </section>
  );
}

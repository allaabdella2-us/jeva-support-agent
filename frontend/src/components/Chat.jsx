import { useEffect, useRef, useState } from "react";
import Jeva from "./Jeva.jsx";
import { StatusPill } from "./Sidebar.jsx";

const THINKING = [
  "Reading your message",
  "Checking your history",
  "Understanding what you need",
  "Checking a few safety rules",
  "Finding the right answer",
];

export const EXAMPLES = [
  { label: "Where's my order?", text: "I've contacted support three times about order A-104. Nobody has helped me. I'm extremely frustrated. Can you please tell me where my order is?" },
  { label: "Follow-up: sign for it?", text: "Thanks! Will I need to sign for it when it arrives?", followUp: true },
  { label: "Charged twice", text: "Hi, I was charged twice for order A-101 last week. Could you please refund the duplicate charge?" },
  { label: "Can't sign in", text: "I'm locked out of my member portal. It keeps saying my password is wrong." },
  { label: "Suspicious prize", risk: true, spoof: "Rewards Team", text: "Congratulations! You've been selected for a $500 wellness reward. Reply with your account password and security code to claim it today." },
  { label: "Not sure who to ask", risk: true, text: "Hi, I have a quick question about my account and something from my last delivery." },
];

// Real LLMs sometimes use **bold** despite the prompt; render it rather than show asterisks.
function formatReply(text) {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part));
}

export default function Chat({ ticket, messages, sending, error, onSend, onExample, onClose, senderLabel }) {
  const [text, setText] = useState("");
  const [tick, setTick] = useState(0);
  const listRef = useRef(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    if (!sending) { setTick(0); return; }
    const t = setInterval(() => setTick((n) => Math.min(n + 1, THINKING.length - 1)), 900);
    return () => clearInterval(t);
  }, [sending]);

  const submit = (e) => {
    e.preventDefault();
    const v = text.trim();
    if (!v || sending) return;
    setText("");
    onSend(v);
  };

  const closed = ticket?.status === "closed";

  return (
    <section className="card chat" aria-label="Chat with Jeva">
      <div className="band chat-band">
        <Jeva size={42} />
        <div className="chat-title">
          <h2>Jeva</h2>
          <p className="status-line">{ticket ? <>{ticket.id} <StatusPill status={ticket.status} /></> : "New conversation"}</p>
        </div>
        {ticket && !closed && (
          <button type="button" className="btn-ghost" onClick={onClose}>Close ticket</button>
        )}
      </div>

      <div className="messages" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="msg agent">
            <Jeva size={30} />
            <div className="bubble">
              Hi, I'm Jeva. I can help with orders, billing and your account. Ask me anything, or try an example below, and watch the pipeline map trace every step.
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === "system" ? (
            <div key={m.id} className="note">{m.content}</div>
          ) : (
            <div key={m.id} className={`msg ${m.role}`}>
              {m.role === "agent" && <Jeva size={30} />}
              <div className="bubble">
                {m.role === "customer" && m.sender && <div className="from">{m.sender}</div>}
                {m.role === "agent" ? formatReply(m.content) : m.content}
              </div>
            </div>
          )
        )}
        {sending && (
          <div className="msg agent">
            <Jeva size={30} />
            <div className="bubble typing">
              <span className="dots"><i /><i /><i /></span>
              {THINKING[tick]}
            </div>
          </div>
        )}
        {error && <div className="note warn">{error}</div>}
      </div>

      <div className="examples">
        <p>Try an example</p>
        <div className="chips">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              className={`chip${ex.risk ? " risk" : ""}`}
              disabled={sending || (ex.followUp && !ticket)}
              title={ex.followUp && !ticket ? "Ask a first question, then follow up on the same ticket" : undefined}
              onClick={() => onExample(ex)}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      <form className="composer" onSubmit={submit}>
        <label htmlFor="msg" className="sr-only">Message Jeva</label>
        <textarea
          id="msg"
          rows={1}
          value={text}
          placeholder={closed ? "This ticket is closed. Start a new conversation." : `Message Jeva as ${senderLabel}`}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }}
        />
        <button className="btn-send" type="submit" disabled={sending || !text.trim()}>Send</button>
      </form>
    </section>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import Jeva from "./components/Jeva.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Chat from "./components/Chat.jsx";
import Inspector from "./components/Inspector.jsx";

const VIEWS = [
  { id: "tickets", label: "Tickets" },
  { id: "chat", label: "Chat" },
  { id: "inspect", label: "Pipeline" },
];

export default function App() {
  const [health, setHealth] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [sender, setSender] = useState({ mode: "customer", customerId: "CUST-1001" });
  const [showAll, setShowAll] = useState(false);
  const [tickets, setTickets] = useState([]);
  const [activeTicketId, setActiveTicketId] = useState(null);
  const [ticket, setTicket] = useState(null);
  const [messages, setMessages] = useState([]);
  const [trace, setTrace] = useState(null);
  const [traceSender, setTraceSender] = useState("");
  const [runKey, setRunKey] = useState(0);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState("chat");
  const [ping, setPing] = useState(false);

  const customer = useMemo(
    () => customers.find((c) => c.id === sender.customerId),
    [customers, sender.customerId]
  );
  const identity = sender.mode === "custom"
    ? { name: sender.name, email: sender.email }
    : { name: customer?.name ?? "", email: customer?.email ?? "" };

  // ---------- loading ----------
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }));
    api.customers().then(setCustomers).catch((e) => setError(e.message));
  }, []);

  const refreshTickets = useCallback(() => {
    const id = !showAll && sender.mode === "customer" ? sender.customerId : undefined;
    return api.tickets(id).then(setTickets).catch((e) => setError(e.message));
  }, [showAll, sender]);

  useEffect(() => { refreshTickets(); }, [refreshTickets]);

  const startNew = () => {
    setActiveTicketId(null);
    setTicket(null);
    setMessages([]);
    setTrace(null);
    setError(null);
    setView("chat");
  };

  const selectTicket = async (id) => {
    setError(null);
    try {
      const data = await api.ticket(id);
      setActiveTicketId(id);
      setTicket(data.ticket);
      setMessages(data.messages);
      setTrace(null); // traces exist for new turns only
      setView("chat");
    } catch (e) {
      setError(e.message);
    }
  };

  const changeSender = (next) => {
    setSender(next);
    if (next.mode !== sender.mode || next.customerId !== sender.customerId) startNew();
  };

  // ---------- sending ----------
  const send = async (text, { newTicket = false, spoofName } = {}) => {
    const who = spoofName ? { name: spoofName, email: identity.email } : identity;
    if (!who.name || !who.email) { setError("Choose who is writing in first."); return; }
    const ticketId = newTicket ? null : activeTicketId;
    if (newTicket) startNew();
    setError(null);
    setSending(true);
    setMessages((m) => [...(newTicket ? [] : m), { id: `tmp-${Date.now()}`, role: "customer", content: text }]);
    try {
      const res = await api.chat({ ticket_id: ticketId, message: text, sender_name: who.name, sender_email: who.email });
      setActiveTicketId(res.ticket_id);
      setTicket(res.ticket);
      setMessages(res.messages.length ? res.messages : [{ id: "tmp", role: "customer", content: text }]);
      if (res.result.route === "no_action") {
        setMessages((m) => [...m, { id: `sys-${Date.now()}`, role: "system", content: "This ticket is already closed, so no action was taken. Start a new conversation." }]);
      }
      setTrace(res.trace);
      setTraceSender(who.name);
      setRunKey((k) => k + 1);
      setPing(true);
      refreshTickets();
    } catch (e) {
      setError(`Couldn't reach Jeva: ${e.message}`);
    } finally {
      setSending(false);
    }
  };

  const runExample = (ex) => send(ex.text, { newTicket: !ex.followUp, spoofName: ex.spoof });

  const closeTicket = async () => {
    if (!activeTicketId) return;
    const res = await api.close(activeTicketId);
    setTicket(res.ticket);
    const data = await api.ticket(activeTicketId);
    setMessages(data.messages);
    refreshTickets();
  };

  const resetDemo = async () => {
    if (!window.confirm("Reset all demo data? Tickets, refunds and memory go back to the seed data.")) return;
    await api.reset();
    startNew();
    refreshTickets();
  };

  const llmLabel = health?.llm_label || "Claude";
  const switchView = (id) => { setView(id); if (id === "inspect") setPing(false); };

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-inner">
          <Jeva size={64} label="Jeva, the support assistant" />
          <div className="hero-text">
            <div className="brand"><i className="brand-mark" />Jeva, the support agent powered by Jev</div>
            <h1>Ask Jeva. See how she works it out.</h1>
          </div>
          <div className="hero-side">
            {health && (
              <div className="modes">
                <span className={`mode ${health.jev_mode}`}
                      title={health.jev_mode === "live" ? `Live: ${health.jev_model}` : `Local stand-in: ${health.jev_note || "no live key"}`}>
                  Jev: {health.jev_mode ?? "offline"}
                </span>
                <span className={`mode ${health.claude_mode}`} title={health.llm_model}>
                  {health.llm_provider === "mock" ? "LLM: mock" : `LLM: ${health.llm_label ?? "Claude"}`}
                </span>
              </div>
            )}
            <button type="button" className="btn-ghost light" onClick={resetDemo}>Reset demo data</button>
          </div>
        </div>
      </header>

      {health?.jev_key_rejected && (
        <div className="notice" role="status">
          <b>Jev is using the local stand-in.</b> {health.jev_note}. Put a valid key in <code>backend/.env</code> and restart the backend to run Jev live.
        </div>
      )}

      <nav className="views" role="tablist" aria-label="Sections">
        {VIEWS.map((v) => (
          <button key={v.id} role="tab" type="button" aria-selected={view === v.id}
                  className={view === v.id ? "on" : ""} onClick={() => switchView(v.id)}>
            {v.label}
            {v.id === "inspect" && ping && view !== "inspect" && <i className="ping" />}
          </button>
        ))}
      </nav>

      <main className="layout" data-view={view}>
        <Sidebar
          customers={customers}
          sender={sender}
          onSenderChange={changeSender}
          tickets={tickets}
          activeTicketId={activeTicketId}
          onSelectTicket={selectTicket}
          onNewConversation={startNew}
          showAll={showAll}
          onToggleShowAll={() => setShowAll((s) => !s)}
        />
        <Chat
          ticket={ticket}
          messages={messages}
          sending={sending}
          error={error}
          onSend={(t) => send(t)}
          onExample={runExample}
          onClose={closeTicket}
          senderLabel={identity.name || "a member"}
        />
        <Inspector trace={trace} senderName={traceSender} runKey={runKey} ticketId={activeTicketId} llmLabel={llmLabel} />
      </main>

      <footer className="tagline">
        <p>Jev understands. Python decides. {llmLabel} explains.</p>
      </footer>
    </div>
  );
}

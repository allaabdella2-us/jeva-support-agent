const STATUS_LABEL = {
  open: "Open",
  awaiting_customer: "Answered",
  escalated: "With a person",
  quarantined: "Quarantined",
  closed: "Closed",
};

export function StatusPill({ status }) {
  return <span className={`pill pill-${status}`}>{STATUS_LABEL[status] || status}</span>;
}

// Choose who is writing in, and pick or start a ticket.
export default function Sidebar({
  customers, sender, onSenderChange, tickets, activeTicketId,
  onSelectTicket, onNewConversation, showAll, onToggleShowAll,
}) {
  const isCustom = sender.mode === "custom";
  return (
    <aside className="card sidebar" aria-label="Tickets">
      <div className="band">
        <h2>Conversations</h2>
        <p className="desc">Write in as any member</p>
      </div>

      <div className="sender">
        <label htmlFor="sender">Writing in as</label>
        <select
          id="sender"
          value={isCustom ? "custom" : sender.customerId}
          onChange={(e) =>
            e.target.value === "custom"
              ? onSenderChange({ mode: "custom", name: "Rewards Team", email: "rewards@claim-prize-now.biz" })
              : onSenderChange({ mode: "customer", customerId: e.target.value })
          }
        >
          {customers.map((c) => (
            <option key={c.id} value={c.id}>{c.name} ({c.plan})</option>
          ))}
          <option value="custom">Someone else…</option>
        </select>
        {isCustom && (
          <div className="custom-sender">
            <label>Display name
              <input value={sender.name} onChange={(e) => onSenderChange({ ...sender, name: e.target.value })} />
            </label>
            <label>Email
              <input type="email" value={sender.email} onChange={(e) => onSenderChange({ ...sender, email: e.target.value })} />
            </label>
          </div>
        )}
        <button className="btn-primary" type="button" onClick={onNewConversation}>New conversation</button>
      </div>

      <div className="ticket-head">
        <span>{showAll ? "All tickets" : "This member's tickets"}</span>
        <button className="link" type="button" onClick={onToggleShowAll}>
          {showAll ? "Show this member" : "Show all"}
        </button>
      </div>
      <ul className="tickets">
        {tickets.length === 0 && <li className="empty-note">No tickets yet. Start a conversation.</li>}
        {tickets.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              className={`ticket${t.id === activeTicketId ? " active" : ""}`}
              onClick={() => onSelectTicket(t.id)}
              aria-current={t.id === activeTicketId ? "true" : undefined}
            >
              <span className="ticket-top">
                <strong>{t.id}</strong>
                <StatusPill status={t.status} />
              </span>
              {showAll && <span className="ticket-who">{t.customer_name || "Unknown sender"}</span>}
              <span className="ticket-last">{t.last_message || "No messages"}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

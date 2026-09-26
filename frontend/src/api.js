// Thin wrapper over the FastAPI backend.
async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),
  customers: () => request("/api/customers"),
  tickets: (customerId) =>
    request(`/api/tickets${customerId ? `?customer_id=${encodeURIComponent(customerId)}` : ""}`),
  ticket: (id) => request(`/api/tickets/${encodeURIComponent(id)}`),
  audit: (id) => request(`/api/tickets/${encodeURIComponent(id)}/audit`),
  history: (customerId) => request(`/api/customers/${encodeURIComponent(customerId)}/history`),
  chat: (body) => request("/api/chat", { method: "POST", body: JSON.stringify(body) }),
  close: (id) => request(`/api/tickets/${encodeURIComponent(id)}/close`, { method: "POST" }),
  reset: () => request("/api/reset", { method: "POST" }),
};

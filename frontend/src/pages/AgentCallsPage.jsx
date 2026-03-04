import { useEffect, useMemo, useState } from "react";

import { readCallLog } from "../lib/callStore";

const STATUS_FILTERS = ["all", "dialing", "active", "connected", "no_answer", "machine", "interested"];

export default function AgentCallsPage() {
  const [entries, setEntries] = useState(readCallLog());
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    const timer = window.setInterval(() => {
      setEntries(readCallLog());
    }, 1500);

    return () => window.clearInterval(timer);
  }, []);

  const filtered = useMemo(() => {
    return entries.filter((entry) => {
      const statusMatch = status === "all" || entry.status === status;
      const queryText = `${entry.leadName || ""} ${entry.phone || ""}`.toLowerCase();
      const queryMatch = !query || queryText.includes(query.toLowerCase());
      return statusMatch && queryMatch;
    });
  }, [entries, query, status]);

  return (
    <div className="view-grid">
      <section className="panel panel--hero">
        <header className="panel-head">
          <h2>Call History</h2>
          <span className="muted">{filtered.length} records</span>
        </header>

        <div className="field-grid field-grid--inline">
          <label className="field">
            Search lead/phone
            <input
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Type name or number"
            />
          </label>

          <label className="field">
            Status
            <select className="input" value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUS_FILTERS.map((item) => (
                <option value={item} key={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Provider ID</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5}>No calls yet. Start calls from Agent Dialer.</td>
                </tr>
              ) : (
                filtered.map((entry) => (
                  <tr key={`${entry.id}-${entry.createdAt}`}>
                    <td>{entry.leadName || "-"}</td>
                    <td>{entry.phone || "-"}</td>
                    <td>
                      <span className="badge badge--idle">{entry.status || "-"}</span>
                    </td>
                    <td>{entry.providerCallId || "-"}</td>
                    <td>{entry.createdAt ? new Date(entry.createdAt).toLocaleString() : "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

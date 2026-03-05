import { useMemo } from "react";

import { readCallLog } from "../lib/callStore";

const AGENT_STATUS = [
  { id: 1, name: "SDR 1", status: "available" },
  { id: 2, name: "SDR 2", status: "busy" },
  { id: 3, name: "SDR 3", status: "wrap_up" },
];

export default function AdminLivePage() {
  const callLog = readCallLog();

  const metrics = useMemo(() => {
    const active = callLog.filter((entry) => ["dialing", "active", "bridged"].includes(entry.status)).length;
    const machine = callLog.filter((entry) => entry.status === "machine").length;
    const connected = callLog.filter((entry) => entry.status === "connected").length;

    return {
      active,
      machine,
      connected,
      total: callLog.length,
    };
  }, [callLog]);

  const recentEvents = callLog.slice(0, 8);

  return (
    <div className="view-grid page page--live">
      <section className="panel panel--hero panel--teal panel--live-hero">
        <header className="panel-head">
          <h2>Live Monitor</h2>
          <span className="muted">Realtime operations snapshot</span>
        </header>

        <div className="kpi-grid">
          <article className="kpi">
            <strong>{metrics.active}</strong>
            <span>Active Calls</span>
          </article>
          <article className="kpi">
            <strong>{metrics.connected}</strong>
            <span>Connected</span>
          </article>
          <article className="kpi">
            <strong>{metrics.machine}</strong>
            <span>Machines</span>
          </article>
          <article className="kpi">
            <strong>{metrics.total}</strong>
            <span>Total Records</span>
          </article>
        </div>
      </section>

      <section className="panel panel--sand panel--live-board">
        <header className="panel-head">
          <h3>SDR State Board</h3>
          <span className="muted">Routing readiness</span>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>SDR</th>
                <th>Status</th>
                <th>Queue Slot</th>
              </tr>
            </thead>
            <tbody>
              {AGENT_STATUS.map((agent, index) => (
                <tr key={agent.id}>
                  <td>{agent.name}</td>
                  <td>
                    <span className={`badge badge--${agent.status}`}>{agent.status}</span>
                  </td>
                  <td>{index + 1}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel panel--cobalt panel--live-events">
        <header className="panel-head">
          <h3>Recent Call Events</h3>
          <span className="muted">Latest 8 entries</span>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Status</th>
                <th>Phone</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {recentEvents.length === 0 ? (
                <tr>
                  <td colSpan={4}>No events yet.</td>
                </tr>
              ) : (
                recentEvents.map((entry) => (
                  <tr key={`${entry.id}-${entry.createdAt}`}>
                    <td>{entry.leadName || "-"}</td>
                    <td>
                      <span className={`badge badge--${entry.status || "idle"}`}>{entry.status || "-"}</span>
                    </td>
                    <td>{entry.phone || "-"}</td>
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

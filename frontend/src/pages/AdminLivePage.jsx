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

  return (
    <div className="view-grid">
      <section className="panel panel--hero">
        <header className="panel-head">
          <h2>Live Monitor</h2>
          <span className="muted">Realtime snapshot</span>
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

      <section className="panel">
        <header className="panel-head">
          <h3>Agent State Board</h3>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Agent</th>
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
    </div>
  );
}

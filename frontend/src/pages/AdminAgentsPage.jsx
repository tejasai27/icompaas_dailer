import { useEffect, useMemo, useState } from "react";

import { request } from "../lib/api";

const STATUS_OPTIONS = ["available", "ringing", "busy", "wrap_up", "offline"];

export default function AdminAgentsPage() {
  const [agents, setAgents] = useState([]);
  const [agentsState, setAgentsState] = useState("idle");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadAgents();
  }, []);

  const stats = useMemo(() => {
    const available = agents.filter((agent) => agent.status === "available").length;
    const busy = agents.filter((agent) => agent.status === "busy").length;
    const wrapUp = agents.filter((agent) => agent.status === "wrap_up").length;
    return {
      total: agents.length,
      available,
      busy,
      wrapUp,
    };
  }, [agents]);

  async function loadAgents() {
    setAgentsState("loading");
    setError("");
    try {
      const data = await request("/api/v1/dialer/agents/");
      setAgents(Array.isArray(data?.agents) ? data.agents : []);
      setAgentsState("ready");
    } catch (requestError) {
      setAgentsState("error");
      setError(requestError.message);
    }
  }

  async function pushStatus(agentId, status) {
    setMessage("");
    setError("");

    try {
      await request(`/api/v1/dialer/agents/${agentId}/status/`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });

      setAgents((current) => current.map((agent) => (agent.id === agentId ? { ...agent, status } : agent)));
      setMessage(`Agent ${agentId} set to ${status}.`);
    } catch (requestError) {
      setError(`Agent ${agentId}: ${requestError.message}`);
    }
  }

  return (
    <div className="view-grid page page--agents">
      <section className="panel panel--hero panel--teal panel--agents-hero">
        <header className="panel-head">
          <h2>Agent Control Board</h2>
          <div className="action-row">
            <span className="muted">Live from AgentProfile</span>
            <button className="btn btn-secondary" type="button" onClick={loadAgents}>
              Refresh
            </button>
          </div>
        </header>

        <div className="kpi-strip kpi-strip--four">
          <article className="metric-pill">
            <span>Total Agents</span>
            <strong>{stats.total}</strong>
          </article>
          <article className="metric-pill">
            <span>Available</span>
            <strong>{stats.available}</strong>
          </article>
          <article className="metric-pill">
            <span>Busy</span>
            <strong>{stats.busy}</strong>
          </article>
          <article className="metric-pill">
            <span>Wrap-Up</span>
            <strong>{stats.wrapUp}</strong>
          </article>
        </div>

        {agentsState === "loading" ? <p className="notice">Loading agents...</p> : null}
        {message ? <p className="notice">{message}</p> : null}
        {error ? <p className="notice notice--error">{error}</p> : null}
      </section>

      <section className="panel panel--cobalt panel--agents-roster">
        <header className="panel-head">
          <h3>Agent Roster</h3>
          <span className={`badge badge--${agentsState === "error" ? "error" : "success"}`}>{agentsState}</span>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Agent</th>
                <th>Current Status</th>
                <th>Update Status</th>
              </tr>
            </thead>
            <tbody>
              {agents.length === 0 ? (
                <tr>
                  <td colSpan={4}>No AgentProfile rows found.</td>
                </tr>
              ) : (
                agents.map((agent) => (
                  <tr key={agent.id}>
                    <td>{agent.id}</td>
                    <td>{agent.display_name}</td>
                    <td>
                      <span className={`badge badge--${agent.status}`}>{agent.status}</span>
                    </td>
                    <td>
                      <div className="chip-row">
                        {STATUS_OPTIONS.map((status) => (
                          <button
                            key={status}
                            type="button"
                            className={`chip ${agent.status === status ? "chip--active" : ""}`}
                            onClick={() => pushStatus(agent.id, status)}
                          >
                            {status}
                          </button>
                        ))}
                      </div>
                    </td>
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

import { useEffect, useMemo, useState } from "react";

import { request } from "../lib/api";
import { appendCallLog } from "../lib/callStore";

const OUTCOME_OPTIONS = [
  "connected",
  "no_answer",
  "busy",
  "machine",
  "interested",
  "not_interested",
  "follow_up",
];

export default function AgentDialerPage() {
  const [lead, setLead] = useState(null);
  const [leadState, setLeadState] = useState("idle");
  const [leadError, setLeadError] = useState("");

  const [agents, setAgents] = useState([]);
  const [agentsState, setAgentsState] = useState("idle");
  const [agentsError, setAgentsError] = useState("");

  const [agentId, setAgentId] = useState("");
  const [agentPhone, setAgentPhone] = useState("");
  const [callerId, setCallerId] = useState("");

  const [callState, setCallState] = useState("idle");
  const [callError, setCallError] = useState("");
  const [currentCall, setCurrentCall] = useState(null);

  const [wrapRemaining, setWrapRemaining] = useState(0);
  const [selectedOutcome, setSelectedOutcome] = useState("");
  const [notes, setNotes] = useState("");

  const hasLead = Boolean(lead?.id);
  const hasAgentId = String(agentId).trim().length > 0;
  const hasAgentPhone = agentPhone.trim().length > 0;
  const canStartCall = hasLead && hasAgentId && hasAgentPhone && callState !== "dialing";

  const startBlockReason = !hasLead
    ? "Load Next Lead first."
    : !hasAgentId
      ? "Select Agent ID."
      : !hasAgentPhone
        ? "Enter Agent Phone."
        : callState === "dialing"
          ? "Call is already dialing."
          : "";

  useEffect(() => {
    loadAgents();
    loadNextLead();
  }, []);

  useEffect(() => {
    if (wrapRemaining <= 0) {
      return;
    }

    const timer = window.setInterval(() => {
      setWrapRemaining((value) => (value <= 1 ? 0 : value - 1));
    }, 1000);

    return () => window.clearInterval(timer);
  }, [wrapRemaining]);

  const leadMeta = useMemo(
    () => [
      ["Lead ID", lead?.id || "-"],
      ["Name", lead?.full_name || "-"],
      ["Company", lead?.company_name || "-"],
      ["Phone", lead?.phone_e164 || "-"],
      ["Email", lead?.email || "-"],
      ["Timezone", lead?.timezone || "-"],
    ],
    [lead]
  );

  async function loadAgents() {
    setAgentsState("loading");
    setAgentsError("");

    try {
      const data = await request("/api/v1/dialer/agents/");
      const rows = Array.isArray(data?.agents) ? data.agents : [];
      setAgents(rows);
      setAgentsState("ready");
      if (!agentId && rows.length > 0) {
        setAgentId(String(rows[0].id));
      }
    } catch (error) {
      setAgentsState("error");
      setAgentsError(error.message);
    }
  }

  async function loadNextLead() {
    setLeadState("loading");
    setLeadError("");
    try {
      const data = await request("/api/v1/dialer/leads/next/");
      setLead(data.lead || null);
      setLeadState("ready");
    } catch (error) {
      setLeadState("error");
      setLeadError(error.message);
    }
  }

  async function startExotelCall() {
    if (!canStartCall) {
      return;
    }

    setCallState("dialing");
    setCallError("");

    try {
      const payload = {
        lead_id: Number(lead.id),
        agent_id: Number(agentId),
        agent_phone: agentPhone.trim(),
      };

      if (callerId.trim()) {
        payload.caller_id = callerId.trim();
      }

      const data = await request("/api/v1/dialer/calls/start/exotel/", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      const call = data.call || null;
      setCurrentCall(call);
      setCallState(call ? "active" : "idle");

      if (call) {
        appendCallLog({
          id: call.id,
          leadId: lead?.id,
          leadName: lead?.full_name || "Unknown lead",
          phone: lead?.phone_e164 || "",
          status: call.status,
          providerCallId: call.provider_call_uuid,
          createdAt: new Date().toISOString(),
        });
      }
    } catch (error) {
      setCallState("error");
      setCallError(error.message);
    }
  }

  function startWrapUp() {
    setWrapRemaining(15);
    setCallState("wrap_up");
  }

  function submitWrapUp() {
    if (!selectedOutcome) {
      return;
    }

    appendCallLog({
      id: currentCall?.id || `local-${Date.now()}`,
      leadId: lead?.id,
      leadName: lead?.full_name || "Unknown lead",
      phone: lead?.phone_e164 || "",
      status: selectedOutcome,
      providerCallId: currentCall?.provider_call_uuid || "",
      notes,
      createdAt: new Date().toISOString(),
    });

    setWrapRemaining(0);
    setSelectedOutcome("");
    setNotes("");
    setCurrentCall(null);
    setCallState("idle");
  }

  return (
    <div className="view-grid view-grid--dialer">
      <section className="panel panel--hero">
        <header className="panel-head">
          <h2>Agent Dialer</h2>
          <button className="btn btn-secondary" onClick={loadNextLead} type="button">
            Load Next Lead
          </button>
        </header>

        <p className="muted">Lead data is fetched from `LeadDialState` queue.</p>

        {leadState === "loading" && <p className="notice">Loading lead queue...</p>}
        {leadState === "error" && <p className="notice notice--error">{leadError}</p>}
        {leadState === "ready" && !hasLead && <p className="notice">No lead available in queue.</p>}

        <div className="meta-grid">
          {leadMeta.map(([label, value]) => (
            <div className="meta-row" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h3>Call Controls</h3>
          <span className={`badge badge--${callState}`}>{callState}</span>
        </header>

        {agentsState === "loading" ? <p className="notice">Loading agent profiles...</p> : null}
        {agentsState === "error" ? <p className="notice notice--error">{agentsError}</p> : null}
        {agentsState === "ready" && agents.length === 0 ? (
          <p className="notice notice--error">No AgentProfile found. Create agents in backend first.</p>
        ) : null}

        <div className="field-grid">
          <label className="field">
            Agent ID (from AgentProfile table)
            <select
              className="input"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
              disabled={agents.length === 0}
            >
              {agents.length === 0 ? <option value="">No agents</option> : null}
              {agents.map((agent) => (
                <option value={agent.id} key={agent.id}>
                  {agent.id} - {agent.display_name} ({agent.status})
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            Agent Phone
            <input
              className="input"
              value={agentPhone}
              onChange={(event) => setAgentPhone(event.target.value)}
              placeholder="+9199XXXXXXXX"
            />
          </label>

          <label className="field">
            Caller ID (optional)
            <input
              className="input"
              value={callerId}
              onChange={(event) => setCallerId(event.target.value)}
              placeholder="Exotel caller id"
            />
          </label>
        </div>

        <div className="action-row">
          <button className="btn" type="button" disabled={!canStartCall} onClick={startExotelCall}>
            Start Exotel Call
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            disabled={!currentCall || callState === "wrap_up"}
            onClick={startWrapUp}
          >
            Simulate Hangup
          </button>
        </div>

        {!canStartCall ? <p className="muted">Start blocked: {startBlockReason}</p> : null}
        {callError ? <p className="notice notice--error">{callError}</p> : null}
        {currentCall ? (
          <div className="call-info">
            <p>
              <strong>Call ID:</strong> {currentCall.id}
            </p>
            <p>
              <strong>Provider Call UUID:</strong> {currentCall.provider_call_uuid || "pending"}
            </p>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <header className="panel-head">
          <h3>Wrap-Up</h3>
          <span className={`badge ${wrapRemaining > 0 ? "badge--warning" : "badge--idle"}`}>
            {wrapRemaining > 0 ? `${wrapRemaining}s remaining` : "idle"}
          </span>
        </header>

        <div className="field-grid">
          <label className="field">
            Call Outcome
            <select
              className="input"
              value={selectedOutcome}
              onChange={(event) => setSelectedOutcome(event.target.value)}
              disabled={wrapRemaining === 0}
            >
              <option value="">Select outcome</option>
              {OUTCOME_OPTIONS.map((outcome) => (
                <option key={outcome} value={outcome}>
                  {outcome}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            Notes
            <textarea
              className="input input--textarea"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              disabled={wrapRemaining === 0}
              placeholder="Summary for CRM"
            />
          </label>
        </div>

        <button
          className="btn"
          type="button"
          disabled={wrapRemaining === 0 || !selectedOutcome}
          onClick={submitWrapUp}
        >
          Submit Wrap-Up
        </button>
      </section>
    </div>
  );
}

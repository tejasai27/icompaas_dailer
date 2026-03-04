import { useMemo, useState } from "react";

const MAPPING_KEY = "icompaas_hubspot_outcome_mapping";

const OUTCOMES = [
  "connected",
  "no_answer",
  "busy",
  "machine",
  "interested",
  "not_interested",
  "follow_up",
];

const HUBSPOT_VALUES = [
  "CONNECTED",
  "NO_ANSWER",
  "BUSY",
  "VOICEMAIL",
  "QUALIFIED",
  "UNQUALIFIED",
  "FOLLOW_UP",
];

function readMapping() {
  try {
    const raw = window.localStorage.getItem(MAPPING_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

export default function AdminHubspotPage() {
  const [mapping, setMapping] = useState(() => {
    const stored = readMapping();
    return OUTCOMES.reduce((acc, outcome) => {
      acc[outcome] = stored[outcome] || "";
      return acc;
    }, {});
  });

  const [message, setMessage] = useState("");

  const stats = useMemo(() => {
    const mapped = OUTCOMES.filter((outcome) => Boolean(mapping[outcome])).length;
    const coverage = Math.round((mapped / OUTCOMES.length) * 100);
    return {
      total: OUTCOMES.length,
      mapped,
      pending: OUTCOMES.length - mapped,
      coverage,
    };
  }, [mapping]);

  function setOutcome(outcome, value) {
    setMapping((current) => ({
      ...current,
      [outcome]: value,
    }));
  }

  function saveMapping() {
    window.localStorage.setItem(MAPPING_KEY, JSON.stringify(mapping));
    setMessage("Mapping saved locally. Connect this to backend HubSpot sync endpoint next.");
  }

  return (
    <div className="view-grid page page--hubspot">
      <section className="panel panel--hero panel--sand panel--hubspot-map">
        <header className="panel-head">
          <h2>HubSpot Outcome Mapping</h2>
          <span className={`badge badge--${stats.coverage === 100 ? "success" : "warning"}`}>
            {stats.coverage}% ready
          </span>
        </header>

        <div className="kpi-strip kpi-strip--four">
          <article className="metric-pill">
            <span>Total Outcomes</span>
            <strong>{stats.total}</strong>
          </article>
          <article className="metric-pill">
            <span>Mapped</span>
            <strong>{stats.mapped}</strong>
          </article>
          <article className="metric-pill">
            <span>Pending</span>
            <strong>{stats.pending}</strong>
          </article>
          <article className="metric-pill">
            <span>Coverage</span>
            <strong>{stats.coverage}%</strong>
          </article>
        </div>

        <p className="notice">Define how dialer outcomes should be stored in HubSpot Call records.</p>

        <div className="field-grid">
          {OUTCOMES.map((outcome) => (
            <label className="field" key={outcome}>
              {outcome}
              <select
                className="input"
                value={mapping[outcome] || ""}
                onChange={(event) => setOutcome(outcome, event.target.value)}
              >
                <option value="">Select HubSpot value</option>
                {HUBSPOT_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        <div className="action-row">
          <button className="btn" type="button" onClick={saveMapping}>
            Save Mapping
          </button>
        </div>

        {message ? <p className="notice">{message}</p> : null}
      </section>

      <section className="panel panel--cobalt panel--hubspot-queue">
        <header className="panel-head">
          <h3>Sync Queue (Preview)</h3>
          <span className="muted">Sample operational queue</span>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Call ID</th>
                <th>Status</th>
                <th>Retries</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>crm-9012</td>
                <td>call-8f31</td>
                <td>
                  <span className="badge badge--success">success</span>
                </td>
                <td>0</td>
              </tr>
              <tr>
                <td>crm-9013</td>
                <td>call-8f32</td>
                <td>
                  <span className="badge badge--warning">pending</span>
                </td>
                <td>1</td>
              </tr>
              <tr>
                <td>crm-9014</td>
                <td>call-8f33</td>
                <td>
                  <span className="badge badge--error">failed</span>
                </td>
                <td>3</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

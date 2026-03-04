import { useMemo, useState } from "react";

import { request } from "../lib/api";

const initialCampaigns = [
  { id: "cmp-1", name: "India SMB March", leads: 2400, status: "running", retryPolicy: "no_answer x3" },
  { id: "cmp-2", name: "Fintech Followups", leads: 680, status: "paused", retryPolicy: "busy x2" },
];

const emptyManualLead = {
  full_name: "",
  phone_e164: "",
  company_name: "",
  email: "",
  owner_hint: "",
  external_id: "",
};

function parseSeparateLeads(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [first = "", second = ""] = line.split(",").map((value) => value.trim());
      if (second) {
        return { full_name: first, phone_e164: second };
      }
      return { phone_e164: first };
    });
}

function formatIngestMessage(result, prefix) {
  return `${prefix}: created ${result.created_count}, existing ${result.duplicate_existing_count}, duplicates in request ${result.duplicate_in_payload_count || 0}, invalid ${result.invalid_count}.`;
}

export default function AdminCampaignsPage() {
  const [campaigns, setCampaigns] = useState(initialCampaigns);
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [retryPolicy, setRetryPolicy] = useState("no_answer x3, busy x2");
  const [file, setFile] = useState(null);

  const [uploadState, setUploadState] = useState("idle");
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");

  const [manualLead, setManualLead] = useState(emptyManualLead);
  const [separateLeadsText, setSeparateLeadsText] = useState("");
  const [manualState, setManualState] = useState("idle");
  const [manualMessage, setManualMessage] = useState("");
  const [manualError, setManualError] = useState("");

  const stats = useMemo(() => {
    const running = campaigns.filter((campaign) => campaign.status === "running").length;
    const paused = campaigns.filter((campaign) => campaign.status === "paused").length;
    const totalLeads = campaigns.reduce((sum, campaign) => sum + (campaign.leads || 0), 0);
    return {
      totalCampaigns: campaigns.length,
      running,
      paused,
      totalLeads,
    };
  }, [campaigns]);

  function appendDraftCampaign(createdCount, label) {
    if (!createdCount) {
      return;
    }

    const campaignName = label || name.trim() || "Manual Intake";
    setCampaigns((current) => [
      {
        id: `cmp-${Date.now()}`,
        name: campaignName,
        leads: createdCount,
        status: "draft",
        retryPolicy,
      },
      ...current,
    ]);
  }

  function clearManualMessages() {
    setManualMessage("");
    setManualError("");
  }

  async function createCampaign(event) {
    event.preventDefault();
    setUploadMessage("");
    setUploadError("");

    if (!name.trim()) {
      setUploadError("Campaign Name is required.");
      return;
    }

    if (!file) {
      setUploadError("Please choose a CSV file.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("campaign_name", name.trim());
    formData.append("timezone", timezone);
    formData.append("retry_policy", retryPolicy);

    setUploadState("uploading");
    try {
      const result = await request("/api/v1/dialer/leads/upload/", {
        method: "POST",
        body: formData,
      });

      setCampaigns((current) => [
        {
          id: `cmp-${Date.now()}`,
          name: name.trim(),
          leads: result.created_count,
          status: "draft",
          retryPolicy,
        },
        ...current,
      ]);

      setUploadMessage(
        `Uploaded ${result.file_name}: created ${result.created_count}, existing ${result.duplicate_existing_count}, duplicates in file ${result.duplicate_in_file_count}, invalid ${result.invalid_count}.`
      );

      setName("");
      setRetryPolicy("no_answer x3, busy x2");
      setFile(null);
      const fileInput = document.getElementById("campaign-leads-csv");
      if (fileInput) {
        fileInput.value = "";
      }
      setUploadState("done");
    } catch (error) {
      setUploadError(error.message);
      setUploadState("error");
    }
  }

  async function addSingleLead(event) {
    event.preventDefault();
    clearManualMessages();

    if (!manualLead.phone_e164.trim()) {
      setManualError("Phone is required for manual lead intake.");
      return;
    }

    setManualState("submitting");

    try {
      const result = await request("/api/v1/dialer/leads/manual/", {
        method: "POST",
        body: JSON.stringify({
          campaign_name: name.trim(),
          timezone,
          leads: [manualLead],
        }),
      });

      appendDraftCampaign(result.created_count, name.trim() || "Manual Intake");
      setManualMessage(formatIngestMessage(result, "Manual lead added"));
      setManualLead(emptyManualLead);
      setManualState("done");
    } catch (error) {
      setManualError(error.message);
      setManualState("error");
    }
  }

  async function addSeparateLeads(event) {
    event.preventDefault();
    clearManualMessages();

    const leads = parseSeparateLeads(separateLeadsText);
    if (leads.length === 0) {
      setManualError("Add at least one lead. Use one line per lead.");
      return;
    }

    setManualState("submitting");

    try {
      const result = await request("/api/v1/dialer/leads/manual/", {
        method: "POST",
        body: JSON.stringify({
          campaign_name: name.trim(),
          timezone,
          leads,
        }),
      });

      appendDraftCampaign(result.created_count, name.trim() || "Manual Batch Intake");
      setManualMessage(formatIngestMessage(result, "Separate leads added"));
      setSeparateLeadsText("");
      setManualState("done");
    } catch (error) {
      setManualError(error.message);
      setManualState("error");
    }
  }

  const isWorking = uploadState === "uploading" || manualState === "submitting";

  return (
    <div className="view-grid page page--campaigns">
      <section className="panel panel--hero panel--teal panel--campaigns-hero">
        <header className="panel-head">
          <h2>Campaign Builder</h2>
          <span className={`badge badge--${isWorking ? "warning" : "idle"}`}>{isWorking ? "saving" : "ready"}</span>
        </header>

        <div className="kpi-strip kpi-strip--four">
          <article className="metric-pill">
            <span>Total Campaigns</span>
            <strong>{stats.totalCampaigns}</strong>
          </article>
          <article className="metric-pill">
            <span>Running</span>
            <strong>{stats.running}</strong>
          </article>
          <article className="metric-pill">
            <span>Paused</span>
            <strong>{stats.paused}</strong>
          </article>
          <article className="metric-pill">
            <span>Total Leads</span>
            <strong>{stats.totalLeads}</strong>
          </article>
        </div>

        <p className="muted">
          Add leads using CSV or manual intake. Manual intake supports one-by-one and separate leads (one per line).
        </p>
      </section>

      <section className="panel panel--sand panel--campaigns-create">
        <header className="panel-head">
          <h3>Create Campaign</h3>
          <span className="muted">Upload + manual intake + queue</span>
        </header>

        <form className="field-grid" onSubmit={createCampaign}>
          <label className="field">
            Campaign Name
            <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
          </label>

          <label className="field">
            Timezone
            <select className="input" value={timezone} onChange={(event) => setTimezone(event.target.value)}>
              <option value="Asia/Kolkata">Asia/Kolkata</option>
              <option value="Asia/Dubai">Asia/Dubai</option>
              <option value="Europe/London">Europe/London</option>
            </select>
          </label>

          <label className="field">
            Retry Policy
            <input
              className="input"
              value={retryPolicy}
              onChange={(event) => setRetryPolicy(event.target.value)}
              placeholder="no_answer x3"
            />
          </label>

          <label className="field">
            CSV Lead List
            <input
              id="campaign-leads-csv"
              className="input"
              type="file"
              accept=".csv"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            {file ? <small>Selected: {file.name}</small> : <small>No file selected</small>}
          </label>

          <div className="action-row">
            <button className="btn" type="submit" disabled={uploadState === "uploading"}>
              {uploadState === "uploading" ? "Uploading..." : "Upload Leads & Create Campaign"}
            </button>
          </div>
        </form>

        {uploadMessage ? <p className="notice">{uploadMessage}</p> : null}
        {uploadError ? <p className="notice notice--error">{uploadError}</p> : null}

        <div className="panel-separator" />

        <header className="panel-head">
          <h3>Manual Lead Intake (No CSV)</h3>
          <span className={`badge badge--${manualState === "submitting" ? "warning" : "idle"}`}>
            {manualState === "submitting" ? "saving" : "ready"}
          </span>
        </header>

        <form className="field-grid" onSubmit={addSingleLead}>
          <label className="field">
            Lead Name
            <input
              className="input"
              value={manualLead.full_name}
              onChange={(event) => setManualLead((current) => ({ ...current, full_name: event.target.value }))}
              placeholder="Jane Smith"
            />
          </label>

          <label className="field">
            Phone
            <input
              className="input"
              value={manualLead.phone_e164}
              onChange={(event) => setManualLead((current) => ({ ...current, phone_e164: event.target.value }))}
              placeholder="+9199XXXXXXXX"
              required
            />
          </label>

          <label className="field">
            Company
            <input
              className="input"
              value={manualLead.company_name}
              onChange={(event) => setManualLead((current) => ({ ...current, company_name: event.target.value }))}
              placeholder="Acme Ltd"
            />
          </label>

          <label className="field">
            Email
            <input
              className="input"
              type="email"
              value={manualLead.email}
              onChange={(event) => setManualLead((current) => ({ ...current, email: event.target.value }))}
              placeholder="jane@acme.com"
            />
          </label>

          <label className="field">
            Owner Hint
            <input
              className="input"
              value={manualLead.owner_hint}
              onChange={(event) => setManualLead((current) => ({ ...current, owner_hint: event.target.value }))}
              placeholder="SDR 1"
            />
          </label>

          <label className="field">
            External ID
            <input
              className="input"
              value={manualLead.external_id}
              onChange={(event) => setManualLead((current) => ({ ...current, external_id: event.target.value }))}
              placeholder="crm-10023"
            />
          </label>

          <div className="action-row">
            <button className="btn" type="submit" disabled={manualState === "submitting"}>
              {manualState === "submitting" ? "Saving..." : "Add Single Lead"}
            </button>
          </div>
        </form>

        <form className="field-grid" onSubmit={addSeparateLeads}>
          <label className="field field--full">
            Separate Leads
            <textarea
              className="input input--textarea"
              value={separateLeadsText}
              onChange={(event) => setSeparateLeadsText(event.target.value)}
              placeholder={"+919900000001\n+919900000002\nJohn Doe, +919900000003"}
            />
            <small>One line per lead. Use `phone` or `name, phone`.</small>
          </label>

          <div className="action-row field--full">
            <button className="btn" type="submit" disabled={manualState === "submitting"}>
              {manualState === "submitting" ? "Saving..." : "Add Separate Leads"}
            </button>
          </div>
        </form>

        {manualMessage ? <p className="notice">{manualMessage}</p> : null}
        {manualError ? <p className="notice notice--error">{manualError}</p> : null}
      </section>

      <section className="panel panel--cobalt panel--campaigns-list">
        <header className="panel-head">
          <h3>Campaign List</h3>
          <span className="muted">Most recent first</span>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Leads (new)</th>
                <th>Status</th>
                <th>Retry Policy</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.id}>
                  <td>{campaign.name}</td>
                  <td>{campaign.leads}</td>
                  <td>
                    <span className={`badge badge--${campaign.status}`}>{campaign.status}</span>
                  </td>
                  <td>{campaign.retryPolicy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

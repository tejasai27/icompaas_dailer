import { useState } from "react";

const initialCampaigns = [
  { id: "cmp-1", name: "India SMB March", leads: 2400, status: "running", retryPolicy: "no_answer x3" },
  { id: "cmp-2", name: "Fintech Followups", leads: 680, status: "paused", retryPolicy: "busy x2" },
];

export default function AdminCampaignsPage() {
  const [campaigns, setCampaigns] = useState(initialCampaigns);
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [retryPolicy, setRetryPolicy] = useState("no_answer x3, busy x2");
  const [fileName, setFileName] = useState("");

  function createCampaign(event) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }

    setCampaigns((current) => [
      {
        id: `cmp-${Date.now()}`,
        name: name.trim(),
        leads: fileName ? 0 : 0,
        status: "draft",
        retryPolicy,
      },
      ...current,
    ]);

    setName("");
    setRetryPolicy("no_answer x3, busy x2");
    setFileName("");
  }

  return (
    <div className="view-grid">
      <section className="panel panel--hero">
        <header className="panel-head">
          <h2>Campaigns</h2>
          <span className="muted">CSV lead ingestion and retry strategy</span>
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
              className="input"
              type="file"
              accept=".csv"
              onChange={(event) => setFileName(event.target.files?.[0]?.name || "")}
            />
            {fileName ? <small className="muted">Selected: {fileName}</small> : null}
          </label>

          <button className="btn" type="submit">
            Create Campaign
          </button>
        </form>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h3>Campaign List</h3>
        </header>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Leads</th>
                <th>Status</th>
                <th>Retry</th>
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

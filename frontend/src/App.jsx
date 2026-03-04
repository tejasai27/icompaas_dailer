import { useEffect, useMemo, useState } from "react";

import AgentCallsPage from "./pages/AgentCallsPage";
import AgentDialerPage from "./pages/AgentDialerPage";
import AdminAgentsPage from "./pages/AdminAgentsPage";
import AdminCampaignsPage from "./pages/AdminCampaignsPage";
import AdminHubspotPage from "./pages/AdminHubspotPage";
import AdminLivePage from "./pages/AdminLivePage";
import { API_BASE, request } from "./lib/api";

const navSections = [
  {
    title: "Agent",
    items: [
      { to: "/agent/dialer", label: "Dialer" },
      { to: "/agent/calls", label: "Calls" },
    ],
  },
  {
    title: "Admin",
    items: [
      { to: "/admin/live", label: "Live" },
      { to: "/admin/campaigns", label: "Campaigns" },
      { to: "/admin/agents", label: "Agents" },
      { to: "/admin/integrations/hubspot", label: "HubSpot" },
    ],
  },
];

const routeMap = {
  "/agent/dialer": AgentDialerPage,
  "/agent/calls": AgentCallsPage,
  "/admin/live": AdminLivePage,
  "/admin/campaigns": AdminCampaignsPage,
  "/admin/agents": AdminAgentsPage,
  "/admin/integrations/hubspot": AdminHubspotPage,
};

const defaultRoute = "/agent/dialer";

function normalizeRoute(pathname) {
  if (routeMap[pathname]) {
    return pathname;
  }
  return defaultRoute;
}

export default function App() {
  const [health, setHealth] = useState({ status: "checking", db: null, cache: null });
  const [route, setRoute] = useState(() => normalizeRoute(window.location.pathname));

  useEffect(() => {
    let mounted = true;

    async function loadHealth() {
      try {
        const data = await request("/api/v1/dialer/health/");
        if (!mounted) {
          return;
        }

        setHealth({
          status: data.ok ? "online" : "degraded",
          db: data.db,
          cache: data.cache,
        });
      } catch {
        if (mounted) {
          setHealth({ status: "down", db: false, cache: false });
        }
      }
    }

    loadHealth();
    const timer = window.setInterval(loadHealth, 7000);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    function onPopState() {
      setRoute(normalizeRoute(window.location.pathname));
    }

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const normalized = normalizeRoute(window.location.pathname);
    if (window.location.pathname !== normalized) {
      window.history.replaceState({}, "", normalized);
      setRoute(normalized);
    }
  }, []);

  const CurrentPage = useMemo(() => routeMap[route] || AgentDialerPage, [route]);

  function navigate(nextRoute) {
    const normalized = normalizeRoute(nextRoute);
    if (normalized === route) {
      return;
    }
    window.history.pushState({}, "", normalized);
    setRoute(normalized);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <h1>iCompaas Dialer</h1>
          <p>Power outbound workspace</p>
        </div>

        {navSections.map((section) => (
          <section key={section.title} className="nav-section">
            <h2>{section.title}</h2>
            <nav>
              {section.items.map((item) => (
                <a
                  key={item.to}
                  href={item.to}
                  onClick={(event) => {
                    event.preventDefault();
                    navigate(item.to);
                  }}
                  className={`nav-link${route === item.to ? " nav-link--active" : ""}`}
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </section>
        ))}
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div>
            <h2>V1 Workspace</h2>
            <p className="muted">Backend: {API_BASE}</p>
          </div>

          <div className="status-row">
            <span className={`badge badge--${health.status}`}>{health.status}</span>
            <span className={`badge ${health.db ? "badge--success" : "badge--error"}`}>db</span>
            <span className={`badge ${health.cache ? "badge--success" : "badge--error"}`}>cache</span>
          </div>
        </header>

        <main className="view">
          <CurrentPage />
        </main>
      </div>
    </div>
  );
}

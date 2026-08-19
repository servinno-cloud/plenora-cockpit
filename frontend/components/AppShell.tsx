"use client";

import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

export function AppShell({ children, environmentLabel = "Geen environment", overallState = "UNKNOWN", observedAt = null, release = "development" }: {
  children: ReactNode; environmentLabel?: string; overallState?: string; observedAt?: string | null; release?: string;
}) {
  const router = useRouter();
  async function logout() {
    const item = document.cookie.split("; ").find(value => value.startsWith("cockpit_csrf="));
    if (!item) return;
    const token = decodeURIComponent(item.split("=")[1]);
    const response = await api("/api/auth/logout", { method: "POST", headers: { "X-CSRF-Token": token } });
    if (response.ok) router.replace("/login");
  }
  const update = observedAt ? new Date(observedAt).toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "short" }) : "Nog geen meting";

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/dashboard" aria-label="Plenora Operations overzicht"><span className="brand-mark" aria-hidden="true">P</span><span><strong>Plenora</strong><small>Operations</small></span></a>
      <nav aria-label="Hoofdnavigatie">
        <a className="active" href="/dashboard" aria-current="page"><span className="nav-icon" aria-hidden="true" />Overzicht</a>
        <span><span className="nav-icon" aria-hidden="true" />Incidenten</span>
        <span><span className="nav-icon" aria-hidden="true" />Historie</span>
      </nav>
      <div className="sidebar-account"><span>Operator</span><button onClick={logout}>Uitloggen</button></div>
    </aside>
    <div className="workspace">
      <header className="context-bar">
        <div className="context-environment"><span>Omgeving</span><b>{environmentLabel}</b></div>
        <dl className="context-meta">
          <div><dt>Status</dt><dd className={`overall state-text-${overallState.toLowerCase()}`}><span className="status-dot" />Overall {overallState}</dd></div>
          <div><dt>Laatste update</dt><dd>{update}</dd></div>
          <div><dt>Release</dt><dd>{release}</dd></div>
        </dl>
      </header>
      {children}
    </div>
  </div>;
}

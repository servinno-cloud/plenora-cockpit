"use client";

import { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "../lib/api";

export function AppShell({ children, environmentLabel = "Geen environment", overallState = "UNKNOWN", observedAt = null, release = "development", currentSection }: {
  children: ReactNode; environmentLabel?: string; overallState?: string; observedAt?: string | null; release?: string; currentSection?: "overview"|"incidents"|"history";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const activeSection = currentSection ?? (pathname.startsWith("/incidenten") ? "incidents" : pathname.startsWith("/historie") ? "history" : "overview");
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
        <a className={activeSection==="overview"?"active":undefined} href="/dashboard" aria-current={activeSection==="overview"?"page":undefined}><span className="nav-icon" aria-hidden="true" />Overzicht</a>
        <a className={activeSection==="incidents"?"active":undefined} href="/incidenten" aria-current={activeSection==="incidents"?"page":undefined}><span className="nav-icon" aria-hidden="true" />Incidenten</a>
        <a className={activeSection==="history"?"active":undefined} href="/historie" aria-current={activeSection==="history"?"page":undefined}><span className="nav-icon" aria-hidden="true" />Historie</a>
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

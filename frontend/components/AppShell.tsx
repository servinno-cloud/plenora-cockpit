"use client";
import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

export function AppShell({ children, environmentLabel = "Geen environment", overallState = "UNKNOWN" }: {
  children: ReactNode; environmentLabel?: string; overallState?: string;
}) {
  const router = useRouter();
  async function logout() {
    const item = document.cookie.split("; ").find(value => value.startsWith("cockpit_csrf="));
    if (!item) return;
    const token = decodeURIComponent(item.split("=")[1]);
    const response = await api("/api/auth/logout", {
      method: "POST", headers: { "X-CSRF-Token": token }
    });
    if (response.ok) router.replace("/login");
  }
  return <div className="shell"><aside><strong>Plenora<br />Operations</strong>
    <nav><a className="active" href="/dashboard">Overzicht</a><span>Incidenten</span><span>Historie</span><button onClick={logout}>Uitloggen</button></nav>
  </aside><div className="workspace"><header><div><span className="eyebrow">Environment</span><b>{environmentLabel}</b></div>
    <div className={`overall state-text-${overallState.toLowerCase()}`}><span className="status-dot" /> Overall {overallState}</div></header>{children}</div></div>;
}

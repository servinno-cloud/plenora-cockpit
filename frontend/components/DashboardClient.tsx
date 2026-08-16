"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { AppShell } from "./AppShell";
import { StatusGrid } from "./StatusGrid";

export function DashboardClient() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => { api("/api/me").then(response => {
    if (!response.ok) router.replace("/login"); else setReady(true);
  }); }, [router]);
  if (!ready) return <main className="login-page"><p>Beveiligde sessie controleren…</p></main>;
  return <AppShell><main className="dashboard"><div className="title-row"><div>
    <span className="eyebrow">Foundation</span><h1>Operations overzicht</h1></div>
    <button disabled>Environment kiezen</button></div><StatusGrid />
    <section className="lower-grid">{["Incidents", "Release"].map(name =>
      <article className="panel" key={name}><h2>{name}</h2><p>Nog geen observaties</p></article>)}</section>
  </main></AppShell>;
}

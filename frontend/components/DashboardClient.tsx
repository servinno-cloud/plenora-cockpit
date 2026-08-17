"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { AppShell } from "./AppShell";
import { Observation, StatusGrid } from "./StatusGrid";

type Environment={id:string;name:string}; type Snapshot={overall_state:string;data_mode:"live"|"fixture";observed_at:string|null;observations:Observation[]}; type Incident={id:string;title:string;severity:string;lifecycle:string;last_seen_at:string};

export function DashboardClient() {
  const router = useRouter();
  const stateOrder:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};
  const [ready,setReady]=useState(false); const [environments,setEnvironments]=useState<Environment[]>([]); const [selected,setSelected]=useState(""); const [snapshot,setSnapshot]=useState<Snapshot|null>(null); const [incidents,setIncidents]=useState<Incident[]>([]);
  useEffect(()=>{Promise.all([api("/api/me"),api("/api/environments"),api("/api/incidents")]).then(async([me,envs,incs])=>{if(!me.ok){router.replace("/login");return}const list=await envs.json();setEnvironments(list);setSelected(list[0]?.id??"");setIncidents(await incs.json());setReady(true)})},[router]);
  useEffect(()=>{if(!selected)return;const load=()=>api(`/api/environments/${selected}/snapshot`).then(r=>r.ok?r.json():null).then(setSnapshot);load();const timer=setInterval(load,30000);return()=>clearInterval(timer)},[selected]);
  if (!ready) return <main className="login-page"><p>Beveiligde sessie controleren…</p></main>;
  return <AppShell><main className="dashboard"><div className="title-row"><div>
    <span className="eyebrow">Real monitoring</span><h1>Operations overzicht</h1></div><select aria-label="Environment" value={selected} onChange={e=>setSelected(e.target.value)}>{environments.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></div>
    <div className={`health-banner state-${(snapshot?.overall_state??"UNKNOWN").toLowerCase()}`}>Overall: {snapshot?.overall_state??"UNKNOWN"}<small>{snapshot?.observed_at?` Laatste meting ${new Date(snapshot.observed_at).toLocaleString("nl-NL")}`:" Nog geen metingen"}</small></div><StatusGrid observations={snapshot?.observations??[]} />{snapshot?.data_mode==="fixture"?<p>Lokale infrastructuurfixture — geen productiebron</p>:null}
    <section className="services-panel panel"><h2>Services</h2><div className="services-list">{["caddy","frontend","backend","db","mail-worker"].map(key=>{const items=(snapshot?.observations??[]).filter(item=>item.target===key&&item.signal.startsWith("service."));const state=items.length?items.reduce((worst,item)=>stateOrder[item.state]>stateOrder[worst]?item.state:worst,"HEALTHY"):"UNKNOWN";return <div className="service-row" key={key}><b>{key==="db"?"PostgreSQL":key==="mail-worker"?"Mailworker":key}</b><span>{state}</span></div>})}</div></section>
    <section className="lower-grid"><article className="panel"><h2>Actieve incidenten</h2>{incidents.filter(i=>i.lifecycle!=="RESOLVED").length?incidents.filter(i=>i.lifecycle!=="RESOLVED").map(i=><div className="incident" key={i.id}><b>{i.severity}</b> {i.title}<small>{new Date(i.last_seen_at).toLocaleString("nl-NL")}</small></div>):<p>Geen actieve incidenten</p>}</article><article className="panel"><h2>Monitoring</h2><p>Observe-only infrastructuurstatus. Geen acties of productietoegang.</p></article></section>
  </main></AppShell>;
}

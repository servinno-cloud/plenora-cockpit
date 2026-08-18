"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { AppShell } from "./AppShell";
import { Observation, StatusGrid } from "./StatusGrid";

type Environment={id:string;name:string;product_name:string};
type Snapshot={overall_state:string;component_states:Record<string,string>;service_states:Record<string,string>;data_mode:"live"|"fixture";observed_at:string|null;observations:Observation[]};
type Incident={id:string;title:string;severity:string;lifecycle:string;last_seen_at:string};
const stateOrder:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};

export function serviceSummary(items:Observation[],apiState?:string){
  const relevant=items.filter(item=>!(item.signal==="service.health"&&item.text_value==="none"));
  const state=apiState??(relevant.length?relevant.reduce((worst,item)=>stateOrder[item.state]>stateOrder[worst]?item.state:worst,"HEALTHY"):"UNKNOWN");
  const health=items.find(item=>item.signal==="service.health")?.text_value;
  const detail=health==="none"?"Draait · geen healthcheck":health==="healthy"?"Docker healthcheck gezond":health==="unhealthy"?"Docker healthcheck ongezond":health==="starting"?"Healthcheck start op":"Geen verse servicestatus";
  return {state,detail};
}

export function DashboardClient() {
  const router = useRouter();
  const [ready,setReady]=useState(false);
  const [environments,setEnvironments]=useState<Environment[]>([]);
  const [selected,setSelected]=useState("");
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const [incidents,setIncidents]=useState<Incident[]>([]);
  useEffect(()=>{Promise.all([api("/api/me"),api("/api/environments"),api("/api/incidents")]).then(async([me,envs,incs])=>{if(!me.ok){router.replace("/login");return}const list=await envs.json();setEnvironments(list);setSelected(list[0]?.id??"");setIncidents(await incs.json());setReady(true)})},[router]);
  useEffect(()=>{if(!selected)return;const load=()=>api(`/api/environments/${selected}/snapshot`).then(r=>r.ok?r.json():null).then(setSnapshot);load();const timer=setInterval(load,30000);return()=>clearInterval(timer)},[selected]);
  if (!ready) return <main className="login-page"><p>Beveiligde sessie controleren…</p></main>;
  const environment=environments.find(item=>item.id===selected);
  const environmentLabel=environment?`${environment.product_name} · ${environment.name}`:"Geen environment";
  const overall=snapshot?.overall_state??"UNKNOWN";
  return <AppShell environmentLabel={environmentLabel} overallState={overall}><main className="dashboard"><div className="title-row"><div>
    <span className="eyebrow">Real monitoring</span><h1>Operations overzicht</h1></div><select aria-label="Environment" value={selected} onChange={e=>setSelected(e.target.value)}>{environments.map(e=><option key={e.id} value={e.id}>{e.product_name} · {e.name}</option>)}</select></div>
    <div className={`health-banner state-${overall.toLowerCase()}`}>Overall: {overall}<small>{snapshot?.observed_at?` Laatste meting ${new Date(snapshot.observed_at).toLocaleString("nl-NL")}`:" Nog geen metingen"}</small></div><StatusGrid observations={snapshot?.observations??[]} componentStates={snapshot?.component_states??{}} />{snapshot?.data_mode==="fixture"?<p>Lokale infrastructuurfixture — geen productiebron</p>:null}
    <section className="services-panel panel"><h2>Services</h2><div className="services-list">{["caddy","frontend","backend","db","mail-worker"].map(key=>{const items=(snapshot?.observations??[]).filter(item=>item.target===key&&item.signal.startsWith("service."));const summary=serviceSummary(items,snapshot?.service_states?.[key]);return <div className={`service-row state-${summary.state.toLowerCase()}`} key={key}><b>{key==="db"?"PostgreSQL":key==="mail-worker"?"Mailworker":key}</b><span>{summary.state}</span><small>{summary.detail}</small></div>})}</div></section>
    <section className="lower-grid"><article className="panel"><h2>Actieve incidenten</h2>{incidents.filter(i=>i.lifecycle!=="RESOLVED").length?incidents.filter(i=>i.lifecycle!=="RESOLVED").map(i=><div className="incident" key={i.id}><b>{i.severity}</b> {i.title}<small>{new Date(i.last_seen_at).toLocaleString("nl-NL")}</small></div>):<p>Geen actieve incidenten</p>}</article><article className="panel"><h2>Monitoring</h2><p>Observe-only infrastructuurstatus. Geen acties of productietoegang.</p><small>Cockpit release: {process.env.NEXT_PUBLIC_COCKPIT_RELEASE??"development"}</small></article></section>
  </main></AppShell>;
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { AppShell } from "./AppShell";
import { Observation, StatusGrid } from "./StatusGrid";

type Environment={id:string;name:string;product_name:string};
type Snapshot={overall_state:string;component_states:Record<string,string>;service_states:Record<string,string>;data_mode:"live"|"fixture";observed_at:string|null;observations:Observation[]};
type Incident={id:string;environment_id:string;component:string;title:string;severity:string;lifecycle:string;first_seen_at:string;last_seen_at:string};
export type AIUsage={status:string;spent_eur:string;budget_eur:string;percentage:number;agents:Array<{agent_key:string;calls:number;spent_eur:string}>};
const stateOrder:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};
const serviceLabels:Record<string,string>={caddy:"Caddy",frontend:"Frontend",backend:"Backend",db:"PostgreSQL","mail-worker":"Mailworker"};

export function displayRelease(value:string){ return /^[0-9a-f]{40}$/i.test(value)?value.slice(0,7):value; }

export function serviceSummary(items:Observation[],apiState?:string){
  const relevant=items.filter(item=>!(item.signal==="service.health"&&item.text_value==="none"));
  const state=apiState??(relevant.length?relevant.reduce((worst,item)=>stateOrder[item.state]>stateOrder[worst]?item.state:worst,"HEALTHY"):"UNKNOWN");
  const health=items.find(item=>item.signal==="service.health")?.text_value;
  const detail=health==="none"?"Draait · geen healthcheck":health==="healthy"?"Docker healthcheck gezond":health==="unhealthy"?"Docker healthcheck ongezond":health==="starting"?"Healthcheck start op":"Geen verse servicestatus";
  return {state,detail};
}

export function AIUsagePanel({usage}:{usage:AIUsage|null}){
  if(!usage)return null;
  const labels:Record<string,string>={disabled:"AI uitgeschakeld",provider_not_configured:"Provider niet geconfigureerd",normal:"Budget normaal",warning:"Budgetwaarschuwing",critical:"Budget kritisch",exhausted:"AI-budget bereikt"};
  const analyst=usage.agents.find(item=>item.agent_key==="operations_analyst");
  return <section className={`panel ai-usage state-${usage.status}`} aria-labelledby="ai-usage-heading"><div className="section-heading"><div><p className="section-kicker">AI-team</p><h2 id="ai-usage-heading">AI Usage</h2></div><b>{labels[usage.status]??usage.status}</b></div><p className="ai-budget"><strong>€ {usage.spent_eur}</strong> / € {usage.budget_eur} deze maand <span>{usage.percentage}%</span></p><div><b>Operations Analyst</b><span>€ {analyst?.spent_eur??"0.00"} · {analyst?.calls??0} analyses</span></div></section>;
}

function restartCount(items:Observation[]){ return items.find(item=>item.signal==="service.restart_count")?.numeric_value; }
function since(value:string){ return new Date(value).toLocaleString("nl-NL",{dateStyle:"short",timeStyle:"short"}); }

export function DashboardClient() {
  const router = useRouter();
  const [ready,setReady]=useState(false);
  const [environments,setEnvironments]=useState<Environment[]>([]);
  const [selected,setSelected]=useState("");
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const [incidents,setIncidents]=useState<Incident[]>([]);
  const [aiUsage,setAIUsage]=useState<AIUsage|null>(null);
  useEffect(()=>{Promise.all([api("/api/me"),api("/api/environments"),api("/api/incidents"),api("/api/ai-usage")]).then(async([me,envs,incs,usage])=>{if(!me.ok){router.replace("/login");return}const list=await envs.json();setEnvironments(list);setSelected(list[0]?.id??"");setIncidents(await incs.json());if(usage.ok)setAIUsage(await usage.json());setReady(true)})},[router]);
  useEffect(()=>{if(!selected)return;const load=()=>api(`/api/environments/${selected}/snapshot`).then(r=>r.ok?r.json():null).then(setSnapshot);load();const timer=setInterval(load,30000);return()=>clearInterval(timer)},[selected]);
  if (!ready) return <main className="login-page"><p>Beveiligde sessie controleren…</p></main>;
  const environment=environments.find(item=>item.id===selected);
  const environmentLabel=environment?`${environment.product_name} · ${environment.name}`:"Geen environment";
  const overall=snapshot?.overall_state??"UNKNOWN";
  const release=displayRelease(process.env.NEXT_PUBLIC_COCKPIT_RELEASE??"development");
  const activeIncidents=incidents.filter(item=>item.environment_id===selected&&item.lifecycle!=="RESOLVED");

  return <AppShell environmentLabel={environmentLabel} overallState={overall} observedAt={snapshot?.observed_at} release={release}>
    <main className="dashboard">
      <div className="title-row"><div><p className="page-kicker">Operationele status</p><h1>Overzicht</h1></div><label className="environment-picker"><span>Environment</span><select aria-label="Environment" value={selected} onChange={e=>setSelected(e.target.value)}>{environments.map(e=><option key={e.id} value={e.id}>{e.product_name} · {e.name}</option>)}</select></label></div>
      <section className={`health-summary state-${overall.toLowerCase()}`} aria-labelledby="health-heading"><div><span className="status-dot" /><span>Overall status</span><strong id="health-heading">{overall}</strong></div><p>{snapshot?.observed_at?`Alle statusinformatie bijgewerkt om ${new Date(snapshot.observed_at).toLocaleTimeString("nl-NL",{hour:"2-digit",minute:"2-digit"})}.`:"Er zijn nog geen actuele metingen ontvangen."}</p></section>
      <StatusGrid observations={snapshot?.observations??[]} componentStates={snapshot?.component_states??{}} />
      {snapshot?.data_mode==="fixture"?<p className="fixture-note">Lokale infrastructuurfixture — geen productiebron</p>:null}
      <AIUsagePanel usage={aiUsage}/>

      <section className="services-panel panel" aria-labelledby="services-heading"><div className="section-heading"><div><p className="section-kicker">Infrastructuur</p><h2 id="services-heading">Services</h2></div><span>Docker runtime</span></div><div className="services-table" role="table" aria-label="Infrastructuurservices"><div className="service-table-head" role="row"><span role="columnheader">Service</span><span role="columnheader">Status</span><span role="columnheader">Healthcheck</span><span role="columnheader">Herstarts</span></div>{["caddy","frontend","backend","db","mail-worker"].map(key=>{const items=(snapshot?.observations??[]).filter(item=>item.target===key&&item.signal.startsWith("service."));const summary=serviceSummary(items,snapshot?.service_states?.[key]);const restarts=restartCount(items);return <div className={`service-row state-${summary.state.toLowerCase()}`} role="row" key={key}><b role="cell">{serviceLabels[key]}</b><span role="cell" className="service-state"><i className="status-dot" />{summary.state}</span><span role="cell">{summary.detail}</span><span role="cell">{restarts??"—"}</span></div>})}</div></section>

      <section className={`incidents-panel panel ${activeIncidents.length?"has-incidents":"no-incidents"}`} aria-labelledby="incidents-heading"><div className="section-heading"><div><p className="section-kicker">Aandacht</p><h2 id="incidents-heading">Actieve incidenten</h2></div><span>{activeIncidents.length} actief</span></div>{activeIncidents.length?<div className="incident-list">{activeIncidents.map(item=><article className={`incident state-${item.severity.toLowerCase()}`} key={item.id}><span className="severity"><i className="status-dot" />{item.severity}</span><div><b>{item.title}</b><small>{item.component} · sinds {since(item.first_seen_at)}</small></div><span>{item.lifecycle}</span></article>)}</div>:<div className="empty-incidents"><span className="status-dot" /><div><b>Geen actieve incidenten</b><small>Alle gemonitorde onderdelen zijn zonder open incident.</small></div></div>}</section>
    </main>
  </AppShell>;
}

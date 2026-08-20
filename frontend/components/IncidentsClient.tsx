"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { AppShell } from "./AppShell";

type AnalysisView={status:"pending"|"available"|"unavailable";trigger_event:string|null;created_at:string|null;summary:string|null;probable_cause:string|null;impact:string|null;confidence:string|null;evidence:string[];recommended_checks:string[];limitations:string[]};
export type IncidentView={id:string;fingerprint:string;component:string;title:string;severity:string;lifecycle:string;first_seen_at:string;last_seen_at:string;resolved_at:string|null;latest_message?:string|null;environment:string;product:string;observations?:Array<{id:string;signal:string;state:string;observed_at:string;message:string|null;code:string}>;analysis?:AnalysisView};

export function incidentDuration(start:string,end:string){
  const seconds=Math.max(0,Math.floor((new Date(end).getTime()-new Date(start).getTime())/1000));
  const hours=Math.floor(seconds/3600);const minutes=Math.floor((seconds%3600)/60);
  return hours?`${hours}u ${minutes}m`:`${minutes}m`;
}
const date=(value:string)=>new Date(value).toLocaleString("nl-NL",{dateStyle:"short",timeStyle:"short"});

export function AnalysisPanel({analysis}:{analysis?:AnalysisView}){
  if(!analysis||analysis.status==="unavailable")return <section className="analysis-panel unavailable"><h3>AI-analyse</h3><p>Analyse niet beschikbaar</p></section>;
  if(analysis.status==="pending")return <section className="analysis-panel pending"><h3>AI-analyse</h3><p>Analyse bezig</p></section>;
  return <section className="analysis-panel available"><div className="analysis-heading"><h3>AI-analyse</h3><span>Confidence {analysis.confidence}</span></div><p className="analysis-note">AI-analyse op basis van beschikbare technische observaties.</p><h4>Samenvatting</h4><p>{analysis.summary}</p><h4>Waarschijnlijke oorzaak</h4><p>{analysis.probable_cause}</p><h4>Bewijs</h4><ul>{analysis.evidence.map(item=><li key={item}>{item}</li>)}</ul><h4>Impact</h4><p>{analysis.impact}</p><h4>Aanbevolen controles</h4><ul>{analysis.recommended_checks.map(item=><li key={item}>{item}</li>)}</ul><h4>Beperkingen</h4><ul>{analysis.limitations.map(item=><li key={item}>{item}</li>)}</ul></section>;
}

export function IncidentList({items,history=false,onSelect}:{items:IncidentView[];history?:boolean;onSelect?:(id:string)=>void}){
  if(!items.length)return <div className="incident-empty"><span className="status-dot"/><div><b>{history?"Nog geen incidenthistorie":"Geen actieve incidenten"}</b><small>{history?"Opgeloste incidenten verschijnen hier.":"Alle gemonitorde onderdelen zijn zonder open incident."}</small></div></div>;
  return <div className="operations-incidents">{items.map(item=>{const end=item.resolved_at??item.last_seen_at;return <article className={`operations-incident state-${item.severity.toLowerCase()}`} key={item.id}><button onClick={()=>onSelect?.(item.id)} aria-label={`Bekijk incident ${item.title}`}><span className="severity"><i className="status-dot"/>{item.severity}</span><span><b>{item.title}</b><small>{item.product} · {item.environment}</small></span><span><b>{item.component}</b><small>{item.lifecycle}</small></span><span><b>{incidentDuration(item.first_seen_at,end)}</b><small>{history?`Opgelost ${date(end)}`:`Sinds ${date(item.first_seen_at)}`}</small></span></button>{!history&&<p>{item.latest_message||"Geen aanvullende technische melding beschikbaar."}</p>}</article>})}</div>;
}

export function IncidentsClient({history=false}:{history?:boolean}){
  const router=useRouter();const [ready,setReady]=useState(false);const [items,setItems]=useState<IncidentView[]>([]);const [detail,setDetail]=useState<IncidentView|null>(null);const [email,setEmail]=useState("not_configured");
  useEffect(()=>{Promise.all([api("/api/me"),api("/api/incidents"),api("/api/notification-status")]).then(async([me,incidents,status])=>{if(!me.ok){router.replace("/login");return}setItems(await incidents.json());setEmail((await status.json()).email);setReady(true)})},[router]);
  function select(id:string){api(`/api/incidents/${id}`).then(response=>response.ok?response.json():null).then(setDetail)}
  if(!ready)return <main className="login-page"><p>Beveiligde sessie controleren…</p></main>;
  const visible=items.filter(item=>history?item.lifecycle==="RESOLVED":item.lifecycle!=="RESOLVED");
  return <AppShell environmentLabel="Alle producten en omgevingen"><main className="dashboard incidents-page"><div className="title-row"><div><p className="page-kicker">Incident operations</p><h1>{history?"Incidenthistorie":"Incidenten"}</h1></div><div className="notification-status"><span>Notificaties</span><b><i className={`status-dot ${email==="active"?"active":""}`}/>E-mail: {email==="active"?"actief":"niet geconfigureerd"}</b></div></div><section className="panel incidents-overview" aria-labelledby="incident-list-heading"><div className="section-heading"><div><p className="section-kicker">{history?"Afgerond":"Operationele aandacht"}</p><h2 id="incident-list-heading">{history?"Opgeloste incidenten":"Actieve incidenten"}</h2></div><span>{visible.length} {history?"opgelost":"actief"}</span></div><IncidentList items={visible} history={history} onSelect={select}/></section>{detail&&<aside className="incident-detail" aria-labelledby="incident-detail-title"><button className="detail-close" onClick={()=>setDetail(null)} aria-label="Sluit incidentdetail">Sluiten</button><p className="section-kicker">Incidentdetail</p><h2 id="incident-detail-title">{detail.title}</h2><dl><div><dt>Status</dt><dd>{detail.lifecycle}</dd></div><div><dt>Severity</dt><dd>{detail.severity}</dd></div><div><dt>Component</dt><dd>{detail.component}</dd></div><div><dt>Geopend</dt><dd>{date(detail.first_seen_at)}</dd></div><div><dt>Laatst gezien</dt><dd>{date(detail.last_seen_at)}</dd></div><div><dt>Technische identiteit</dt><dd><code>{detail.fingerprint}</code></dd></div></dl><AnalysisPanel analysis={detail.analysis}/><h3>Relevante signalen</h3><ol>{detail.observations?.map(value=><li key={value.id}><b>{value.signal} · {value.state}</b><span>{date(value.observed_at)}</span><p>{value.message||value.code}</p></li>)}</ol></aside>}</main></AppShell>;
}

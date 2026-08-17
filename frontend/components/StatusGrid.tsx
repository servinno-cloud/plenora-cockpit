export type Observation={target:string|null;component:string;signal:string;code:string;state:string;observed_at:string;numeric_value:number|null;text_value:string|null;unit:string|null;message:string|null;source:string;stale?:boolean};
const components=["Web","Backend","Database","Mail","Backups","Host"];
const rank:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};
export function StatusGrid({observations}:{observations:Observation[]}){
 return <section className="status-grid" aria-label="Systeemstatus">{components.map(name=>{
  const matches=observations.filter(item=>item.component.toLowerCase()===name.toLowerCase());
  const state=matches.length?matches.reduce((worst,item)=>rank[item.state]>rank[worst]?item.state:worst,"HEALTHY"):"UNKNOWN";
  const metrics=matches.filter(item=>["db.latency_ms","db.connections_percent","mail.queue_count","mail.failed_count","service.uptime_seconds"].includes(item.signal)).slice(0,2);
  const disabled=matches.some(item=>item.code==="integration_disabled");
  return <article className={`status-card state-${state.toLowerCase()}`} key={name}><div><span className="status-dot" />{state}</div><h2>{name}</h2><p>{disabled?"Integratie nog niet gekoppeld":metrics.length?metrics.map(item=>`${item.signal.split(".").at(-1)} ${item.numeric_value} ${item.unit??""}`).join(" · "):matches.length?"Technische signalen actueel":"Nog geen verse observatie"}</p></article>})}</section>
}

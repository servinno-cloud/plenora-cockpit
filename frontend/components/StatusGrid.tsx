export type Observation={target:string|null;component:string;signal:string;code:string;state:string;observed_at:string;numeric_value:number|null;text_value:string|null;unit:string|null;message:string|null;source:string;stale?:boolean};
const components=["Web","Backend","Database","Mail","Backups","Host"];
const rank:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};

function find(items:Observation[], signal:string){return items.find(item=>item.signal===signal)}
function numeric(items:Observation[], signal:string){return find(items,signal)?.numeric_value ?? null}
function text(items:Observation[], signal:string){return find(items,signal)?.text_value ?? null}
function bytes(value:number){
  if(value>=1024**3)return `${(value/1024**3).toFixed(1)} GB`;
  if(value>=1024**2)return `${(value/1024**2).toFixed(1)} MB`;
  return `${Math.round(value/1024)} KB`;
}
function duration(seconds:number){
  const days=Math.floor(seconds/86400); if(days)return `${days} d`;
  const hours=Math.floor(seconds/3600); return `${hours} u`;
}
function date(value:string){return new Date(value).toLocaleString("nl-NL",{dateStyle:"short",timeStyle:"short"})}

export function metricLines(component:string,items:Observation[]):string[]{
  const lines:string[]=[];
  if(component==="Web"){
    const status=numeric(items,"https.status_code"); if(status!==null)lines.push(`HTTP ${status}`);
    const latency=numeric(items,"https.latency_ms"); if(latency!==null)lines.push(`Latency ${latency} ms`);
    const tls=numeric(items,"tls.days_remaining"); if(tls!==null)lines.push(`TLS ${tls} dagen`);
    const health=numeric(items,"health.status_code"); if(health!==null)lines.push(`Health endpoint ${health}`);
  }else if(component==="Backups"){
    const success=text(items,"backup.last_success_at"); if(success)lines.push(`Laatste succes ${date(success)}`);
    const status=text(items,"backup.status"); if(status)lines.push(`Status ${status==="success"?"geslaagd":"mislukt"}`);
    const checksum=find(items,"backup.checksum_verified"); if(checksum)lines.push(checksum.state==="HEALTHY"?"Checksum geverifieerd":"Checksum vereist aandacht");
    const database=numeric(items,"backup.database_bytes"); if(database!==null)lines.push(`Database ${bytes(database)}`);
    const media=numeric(items,"backup.media_bytes"); if(media!==null)lines.push(`Media ${bytes(media)}`);
  }else if(component==="Host"){
    const uptime=numeric(items,"host.uptime_seconds"); if(uptime!==null)lines.push(`Uptime ${duration(uptime)}`);
    const load=numeric(items,"host.load_1m"); if(load!==null)lines.push(`Load 1m ${load}`);
    const used=numeric(items,"disk.root.used_bytes"),free=numeric(items,"disk.root.free_bytes");
    if(used!==null&&free!==null&&used+free>0)lines.push(`Rootdisk ${Math.round(used/(used+free)*100)}% gebruikt`);
    const inodes=numeric(items,"disk.root.inode_used_percent"); if(inodes!==null)lines.push(`Inodes ${inodes}%`);
  }else if(component==="Database"){
    const reachable=find(items,"db.reachable"); if(reachable)lines.push(reachable.state==="HEALTHY"?"Bereikbaar":"Niet bereikbaar");
    const version=numeric(items,"db.version_major"); if(version!==null)lines.push(`PostgreSQL ${version}`);
    const latency=numeric(items,"db.latency_ms"); if(latency!==null)lines.push(`Latency ${latency} ms`);
    const connections=numeric(items,"db.connections_percent"); if(connections!==null)lines.push(`Connecties ${connections}%`);
    const migrations=find(items,"db.migration_current");
    if(migrations?.state==="UNKNOWN")lines.push("Migratiestatus niet gekoppeld");
  }else if(component==="Backend"){
    const running=find(items,"service.running"); if(running)lines.push(running.state==="HEALTHY"?"Service draait":"Service niet actief");
    const health=text(items,"service.health");
    if(health==="healthy")lines.push("Docker healthcheck gezond");
    else if(health==="none")lines.push("Draait · geen healthcheck");
    const restarts=numeric(items,"service.restart_count"); if(restarts!==null)lines.push(`Herstarts ${restarts}`);
  }
  return lines;
}

export function StatusGrid({observations,componentStates={}}:{observations:Observation[];componentStates?:Record<string,string>}){
 return <section className="status-grid" aria-label="Systeemstatus">{components.map(name=>{
  const matches=observations.filter(item=>item.component.toLowerCase()===name.toLowerCase());
  const derived=matches.length?matches.reduce((worst,item)=>rank[item.state]>rank[worst]?item.state:worst,"HEALTHY"):"UNKNOWN";
  const state=componentStates[name]??derived;
  const metrics=metricLines(name,matches);
  const disabled=name==="Mail"&&matches.some(item=>item.code==="integration_disabled");
  const message=disabled?["Integratie nog niet gekoppeld"]:metrics.length?metrics:matches.length?["Technische signalen actueel"]:["Nog geen verse observatie"];
  return <article className={`status-card state-${state.toLowerCase()}`} key={name}><div><span className="status-dot" />{state}</div><h2>{name}</h2><ul className="metric-list">{message.map(line=><li key={line}>{line}</li>)}</ul></article>})}</section>
}

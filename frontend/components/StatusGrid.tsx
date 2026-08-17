export type Observation={component:string;code:string;state:string;observed_at:string;numeric_value:number|null;unit:string|null;message:string|null;source:string};
const components=["Web","Backend","Database","Mail","Backups","Host"];
const rank:Record<string,number>={HEALTHY:0,DEGRADED:1,WARNING:2,UNKNOWN:3,CRITICAL:4};
export function StatusGrid({observations}:{observations:Observation[]}){
 return <section className="status-grid" aria-label="Systeemstatus">{components.map(name=>{
  const matches=observations.filter(item=>item.component.toLowerCase()===name.toLowerCase());
  const state=matches.length?matches.reduce((worst,item)=>rank[item.state]>rank[worst]?item.state:worst,"HEALTHY"):"UNKNOWN"; const latest=matches[0];
  return <article className={`status-card state-${state.toLowerCase()}`} key={name}><div><span className="status-dot" />{state}</div><h2>{name}</h2><p>{latest?`${latest.code}${latest.numeric_value!==null?`: ${latest.numeric_value} ${latest.unit??""}`:""}`:"Nog geen verse observatie"}</p></article>})}</section>
}

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AppShell } from "./AppShell";
import { AIUsagePanel, displayRelease, serviceSummary } from "./DashboardClient";
import { LoginForm } from "./LoginForm";
import { StatusGrid } from "./StatusGrid";
import { AnalysisPanel, IncidentList, incidentDuration } from "./IncidentsClient";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname:()=>"/dashboard" }));
afterEach(cleanup);

test("login form exposes secure operator state", () => {
  render(<LoginForm />); expect(screen.getByText("Veilig inloggen")).toBeInTheDocument();
  expect(screen.getByLabelText("Wachtwoord")).toHaveAttribute("type", "password");
});
test("authenticated shell has navigation", () => {
  render(<AppShell environmentLabel="Plenora · Production" overallState="HEALTHY"><span>Content</span></AppShell>);
  expect(screen.getByText("Overzicht")).toBeInTheDocument();
  expect(screen.getByText("Plenora · Production")).toBeInTheDocument();
  expect(screen.getByText("Overall HEALTHY")).toBeInTheDocument();
});

const base={target:"database",component:"Database",code:"ok",state:"HEALTHY",observed_at:"2026-08-18T12:00:00Z",numeric_value:null,text_value:null,unit:null,message:null,source:"database_contract"};

test("healthy database renders metrics and keeps migration status separate",()=>{
  render(<StatusGrid componentStates={{Database:"HEALTHY"}} observations={[
    {...base,signal:"db.version_major",numeric_value:16},
    {...base,signal:"db.latency_ms",numeric_value:8},
    {...base,signal:"db.connections_percent",numeric_value:12.5},
    {...base,signal:"db.migration_current",state:"UNKNOWN"},
  ]}/>);
  expect(screen.getByText("PostgreSQL 16")).toBeInTheDocument();
  expect(screen.getByText("Latency 8 ms")).toBeInTheDocument();
  expect(screen.getByText("Migratiestatus niet gekoppeld")).toBeInTheDocument();
});

test("mail disabled is understandable and no unavailable metrics are invented",()=>{
  render(<StatusGrid observations={[
    {...base,target:"mail",component:"Mail",signal:"mail.provider_state",state:"UNKNOWN",code:"signal_unknown",message:"Integratie nog niet gekoppeld",source:"mail_contract"},
    {...base,target:"web",component:"Web",signal:"https.latency_ms",numeric_value:42,unit:"ms",source:"external_https"},
  ]}/>);
  expect(screen.getByText("Integratie nog niet gekoppeld")).toBeInTheDocument();
  expect(screen.getByText("Latency 42 ms")).toBeInTheDocument();
  expect(screen.queryByText(/TLS /)).not.toBeInTheDocument();
  expect(screen.queryByText(/HTTP /)).not.toBeInTheDocument();
  const mailCard=screen.getByRole("heading",{name:"Mail"}).closest("article");
  expect(mailCard).not.toBeNull();
  expect(within(mailCard!).queryByText("Technische signalen actueel")).not.toBeInTheDocument();
});

test("release presentation shortens only full git hashes",()=>{
  expect(displayRelease("7cae9fd0123456789abcdef0123456789abcdef0")).toBe("7cae9fd");
  expect(displayRelease("release-2026.08-production")).toBe("release-2026.08-production");
});

test("service without healthcheck is healthy when running and unhealthy remains critical",()=>{
  const running={...base,target:"caddy",component:"Services",signal:"service.running",source:"service_boundary"};
  const none={...running,signal:"service.health",state:"UNKNOWN",text_value:"none"};
  expect(serviceSummary([running,none])).toEqual({state:"HEALTHY",detail:"Draait · geen healthcheck"});
  expect(serviceSummary([{...none,state:"CRITICAL",text_value:"unhealthy"}])).toEqual({state:"CRITICAL",detail:"Docker healthcheck ongezond"});
});
test("monitoring cards are explicitly unknown without data", () => {
  render(<StatusGrid observations={[]} />); expect(screen.getAllByText("Nog geen verse observatie")).toHaveLength(6);
});

test("incident operations expose active context and resolved history",()=>{
  const incident={id:"one",fingerprint:"abc",component:"Backups",title:"Backupstatus vereist aandacht",severity:"CRITICAL",lifecycle:"OPEN",first_seen_at:"2026-08-18T10:00:00Z",last_seen_at:"2026-08-18T11:15:00Z",resolved_at:null,latest_message:"Checksum kon niet worden bevestigd",environment:"Production",product:"Plenora"};
  render(<IncidentList items={[incident]}/>);
  expect(screen.getByText("Backupstatus vereist aandacht")).toBeInTheDocument();
  expect(screen.getByText("Checksum kon niet worden bevestigd")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:/Bekijk incident/})).toBeInTheDocument();
  expect(incidentDuration(incident.first_seen_at,incident.last_seen_at)).toBe("1u 15m");
  cleanup();
  render(<IncidentList items={[{...incident,lifecycle:"RESOLVED",resolved_at:incident.last_seen_at}]} history/>);
  expect(screen.getByText(/Opgelost/)).toBeInTheDocument();
});

test("operations analyst renders pending available and unavailable states",()=>{
  const analysis={status:"available" as const,trigger_event:"OPENED",created_at:"2026-08-19T12:00:00Z",summary:"Technische samenvatting",probable_cause:"Onvoldoende bewijs voor een zekere oorzaak.",impact:"Mogelijk tragere responses.",confidence:"MEDIUM",evidence:["Latency is verhoogd."],recommended_checks:["Controleer de latencytrend."],limitations:["Geen logs beschikbaar."]};
  const {rerender}=render(<AnalysisPanel analysis={analysis}/>);
  expect(screen.getByText("Technische samenvatting")).toBeInTheDocument();
  expect(screen.getByText("Confidence MEDIUM")).toBeInTheDocument();
  expect(screen.getByText(/AI-analyse op basis/)).toBeInTheDocument();
  rerender(<AnalysisPanel analysis={{...analysis,status:"pending"}}/>);
  expect(screen.getByText("Analyse bezig")).toBeInTheDocument();
  rerender(<AnalysisPanel analysis={{...analysis,status:"unavailable"}}/>);
  expect(screen.getByText("Analyse niet beschikbaar")).toBeInTheDocument();
});

test("AI usage renders the shared cap and exhausted state",()=>{
  render(<AIUsagePanel usage={{status:"exhausted",spent_eur:"100.00",budget_eur:"100.00",percentage:100,agents:[{agent_key:"operations_analyst",calls:42,spent_eur:"100.00"}]}}/>);
  expect(screen.getByText("AI-budget bereikt")).toBeInTheDocument();
  expect(screen.getByText("€ 100.00 · 42 analyses")).toBeInTheDocument();
});

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AppShell } from "./AppShell";
import { serviceSummary } from "./DashboardClient";
import { LoginForm } from "./LoginForm";
import { StatusGrid } from "./StatusGrid";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
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
    {...base,target:"mail",component:"Mail",signal:"mail.provider_state",state:"UNKNOWN",code:"integration_disabled",source:"mail_contract"},
    {...base,target:"web",component:"Web",signal:"https.latency_ms",numeric_value:42,unit:"ms",source:"external_https"},
  ]}/>);
  expect(screen.getByText("Integratie nog niet gekoppeld")).toBeInTheDocument();
  expect(screen.getByText("Latency 42 ms")).toBeInTheDocument();
  expect(screen.queryByText(/TLS /)).not.toBeInTheDocument();
  expect(screen.queryByText(/HTTP /)).not.toBeInTheDocument();
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

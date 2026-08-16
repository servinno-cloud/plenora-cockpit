import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { AppShell } from "./AppShell";
import { LoginForm } from "./LoginForm";
import { StatusGrid } from "./StatusGrid";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

test("login form exposes secure operator state", () => {
  render(<LoginForm />); expect(screen.getByText("Veilig inloggen")).toBeInTheDocument();
  expect(screen.getByLabelText("Wachtwoord")).toHaveAttribute("type", "password");
});
test("authenticated shell has navigation", () => {
  render(<AppShell><span>Content</span></AppShell>); expect(screen.getByText("Overzicht")).toBeInTheDocument();
});
test("all foundation cards are explicitly unknown", () => {
  render(<StatusGrid />); expect(screen.getAllByText("Nog geen observaties")).toHaveLength(6);
});

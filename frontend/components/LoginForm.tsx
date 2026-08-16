"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    const csrfResponse = await api("/api/auth/csrf");
    const { csrf_token } = await csrfResponse.json();
    const response = await api("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") })
    });
    setBusy(false);
    if (!response.ok) { setError("Inloggen is niet gelukt."); return; }
    router.push("/dashboard");
  }

  return <form className="login-card" onSubmit={submit}>
    <span className="eyebrow">Plenora Operations</span><h1>Veilig inloggen</h1>
    <p>Alleen voor geautoriseerde operators.</p>
    <label>E-mailadres<input name="email" type="email" autoComplete="username" required /></label>
    <label>Wachtwoord<input name="password" type="password" autoComplete="current-password" required /></label>
    {error && <div role="alert" className="error">{error}</div>}
    <button disabled={busy}>{busy ? "Controleren…" : "Inloggen"}</button>
  </form>;
}

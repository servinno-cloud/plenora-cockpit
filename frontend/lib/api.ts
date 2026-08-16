export const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100";

export async function api(path: string, init?: RequestInit) {
  return fetch(`${apiBase}${path}`, { ...init, credentials: "include", cache: "no-store" });
}

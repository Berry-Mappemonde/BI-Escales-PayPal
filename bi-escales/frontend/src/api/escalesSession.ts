const STORAGE_KEY = "escalesCaptainSession";

/** Stable browser tab session id for captain rate limits (sent as X-Escales-Session). */
export function escalesSessionId(): string {
  try {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    return "anonymous";
  }
}

export function captainSessionHeaders(): Record<string, string> {
  return { "X-Escales-Session": escalesSessionId() };
}

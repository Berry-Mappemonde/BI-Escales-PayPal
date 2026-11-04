const STORAGE_KEY = "bi-escales-pledge-ids";

export function loadTrackedPledgeIds(): string[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string" && id.length > 0);
  } catch {
    return [];
  }
}

export function saveTrackedPledgeIds(ids: string[]): void {
  const unique = [...new Set(ids)];
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(unique));
}

export function trackPledgeId(id: string): string[] {
  const next = [...new Set([...loadTrackedPledgeIds(), id])];
  saveTrackedPledgeIds(next);
  return next;
}

export function untrackPledgeId(id: string): string[] {
  const next = loadTrackedPledgeIds().filter((x) => x !== id);
  saveTrackedPledgeIds(next);
  return next;
}

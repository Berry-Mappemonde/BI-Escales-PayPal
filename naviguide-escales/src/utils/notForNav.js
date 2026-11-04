export const NOT_FOR_NAV_STORAGE_KEY = "ng.sim.notForNav.accepted";
export const NOT_FOR_NAV_VERSION = "2026-09-14.v1";

export function readNotForNavAccepted(storage) {
  try {
    const raw = (storage || localStorage).getItem(NOT_FOR_NAV_STORAGE_KEY);
    if (!raw) return false;
    const rec = JSON.parse(raw);
    return rec?.version === NOT_FOR_NAV_VERSION;
  } catch (_) {
    return false;
  }
}

export function writeNotForNavAccepted(storage) {
  const rec = { version: NOT_FOR_NAV_VERSION, at: new Date().toISOString() };
  try {
    (storage || localStorage).setItem(NOT_FOR_NAV_STORAGE_KEY, JSON.stringify(rec));
  } catch (_) { /* quota */ }
  return rec;
}

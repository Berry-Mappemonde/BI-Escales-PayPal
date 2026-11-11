/**
 * The pledges this browser made, for the demo treasurer (issue #145).
 *
 * When the browser creates a pledge it chooses the request id (`PayPal-Request-Id`).
 * The server keeps it on the pledge and never sends it back, so only this browser
 * knows it: presenting it later is the proof that the pledge is its own. This module
 * remembers the pairs; the server checks them on every demo action.
 *
 * Sandbox demo only. The stored value gives no access to anything but that one
 * sandbox pledge, and only while demo treasurer mode is on.
 */
const STORE = "escales.demo.pledge-keys";
/** The server accepts at most this many pairs per call; the oldest are dropped first. */
export const OWN_PLEDGES_MAX = 50;

type Pairs = Record<string, string>;

function read(): Pairs {
  try {
    const raw = localStorage.getItem(STORE);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Pairs = {};
    for (const [id, key] of Object.entries(parsed as Record<string, unknown>)) {
      if (id && typeof key === "string" && key) out[id] = key;
    }
    return out;
  } catch {
    return {}; // private mode, or a value that is not ours
  }
}

/** Remembers that this browser made `pledgeId` with `key`. Never throws. */
export function rememberPledgeKey(pledgeId: string | null | undefined, key: string | null | undefined): void {
  const id = String(pledgeId || "").trim();
  const value = String(key || "").trim();
  if (!id || !value) return;
  try {
    const pairs = read();
    delete pairs[id]; // re-inserted last: insertion order is age
    pairs[id] = value;
    const ids = Object.keys(pairs);
    for (const old of ids.slice(0, Math.max(0, ids.length - OWN_PLEDGES_MAX))) delete pairs[old];
    localStorage.setItem(STORE, JSON.stringify(pairs));
  } catch {
    /* private mode: the pledge is simply not playable from the demo page */
  }
}

/** The request id this browser used for `pledgeId`, if it made it. */
export function pledgeKey(pledgeId: string): string | null {
  return read()[pledgeId] ?? null;
}

/** Every pledge this browser remembers making, newest last. */
export function ownPledgePairs(): Array<{ id: string; key: string }> {
  return Object.entries(read()).map(([id, key]) => ({ id, key }));
}

/** Tests only. */
export function forgetOwnPledgesForTests(): void {
  try {
    localStorage.removeItem(STORE);
  } catch {
    /* nothing to forget */
  }
}

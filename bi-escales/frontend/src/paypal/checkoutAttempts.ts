import { authorizePledge, registerVault } from "../api/escales";

export type CheckoutAttempt = Readonly<{
  key: string; revision: number; pledgeId: string; orderId?: string;
  amount: string; currency: string; milestone: string; target: string;
  mode: "AUTHORIZE" | "VAULT"; path: string; verified?: boolean;
}>;
const STORAGE = "escales-v6-attempts";
function storedAttempts(): CheckoutAttempt[] {
  try { const data: unknown = JSON.parse(sessionStorage.getItem(STORAGE) || "[]"); return Array.isArray(data) ? data.filter(a => a && typeof a.pledgeId === "string" && typeof a.key === "string" && typeof a.amount === "string" && typeof a.currency === "string" && typeof a.revision === "number" && ["AUTHORIZE", "VAULT"].includes(a.mode) && typeof a.path === "string") : []; }
  catch { return []; }
}
export function attempts(): CheckoutAttempt[] { return storedAttempts().filter(a => a.path === location.pathname); }
export function rememberAttempt(attempt: CheckoutAttempt): CheckoutAttempt {
  const frozen = Object.freeze({ ...attempt });
  try { sessionStorage.setItem(STORAGE, JSON.stringify([...storedAttempts().filter(a => a.pledgeId !== attempt.pledgeId), frozen].slice(-20))); } catch { /* memory callback correlation remains available */ }
  return frozen;
}
export function returnedAttempt(orderId?: string, mode: "AUTHORIZE" | "VAULT" = "AUTHORIZE"): CheckoutAttempt | undefined {
  const rows = attempts().filter(a => !a.verified && a.mode === mode && (!orderId || a.orderId === orderId));
  return rows.length === 1 ? rows[0] : undefined; // Ambiguous or cross-page returns fail closed.
}
const receipts = new Map<string, ReturnType<typeof authorizePledge>>();
export function reconcileAttempt(id: string, vault = false, approvalToken?: string) {
  const logicalKey = attempts().find(attempt => attempt.pledgeId === id)?.key;
  const key = `${logicalKey || "legacy"}:${vault ? "vault" : "order"}:${id}`;
  let pending = receipts.get(key);
  if (!pending) {
    pending = (vault ? (approvalToken ? registerVault(id, approvalToken) : registerVault(id)) : authorizePledge(id)).then(receipt => {
      try { sessionStorage.setItem(STORAGE, JSON.stringify(storedAttempts().map(a => a.pledgeId === id ? { ...a, verified: true } : a))); } catch { /* Server receipt remains authoritative. */ }
      return receipt;
    }).catch(error => { receipts.delete(key); throw error; }).finally(() => { if (!logicalKey) receipts.delete(key); });
    receipts.set(key, pending);
  }
  return pending;
}
const resumes = new Map<string, Promise<void>>();
export async function resumeCheckout(session: { hasReturned?: () => boolean; resume?: () => Promise<void> }, vault: boolean) {
  if (!session.hasReturned?.() || !session.resume) return;
  const attempt = returnedAttempt(undefined, vault ? "VAULT" : "AUTHORIZE");
  if (!attempt) return; // Existing App return handlers still reconcile legacy URL returns.
  const key = `${attempt.key}:${attempt.pledgeId}`;
  let pending = resumes.get(key);
  if (!pending) { pending = session.resume().catch(error => { resumes.delete(key); throw error; }); resumes.set(key, pending); }
  await pending;
}

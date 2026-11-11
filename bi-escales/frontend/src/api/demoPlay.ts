/**
 * Demo treasurer API (issue #145): a visitor plays the treasurer on the pledges their
 * own browser made. Kept apart from the treasurer's keyed API on purpose: these calls
 * carry no treasurer key, only the proof that the pledge is this browser's own.
 */
import type { PublicPledge } from "./types";
import { ownPledgePairs, pledgeKey } from "../demo/ownPledges";

const API_BASE = String(import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
const url = (path: string) => `${API_BASE}${path}`;

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body?.detail === "string" && body.detail) return body.detail;
  } catch {
    /* not JSON */
  }
  return `HTTP ${res.status}`;
}

/** One of this browser's own pledges in the demo treasurer loop (issue #145). */
export type DemoPlayAction = "simulate_arrival" | "approve" | "capture" | "void" | "refund";

export interface DemoPlay {
  pledge_id: string;
  status: string;
  arrival_simulated_at: string | null;
  approved_at: string | null;
  /** What may be done next, in order. Empty when the loop is over. */
  actions: DemoPlayAction[];
}

/** Which of the pledges this browser remembers it may play with. No request when it remembers none. */
export async function fetchOwnDemoPledges(): Promise<DemoPlay[]> {
  const pledges = ownPledgePairs();
  if (!pledges.length) return [];
  const res = await fetch(url("/api/escales/demo/pledges/own"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pledges }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const body = (await res.json()) as { own?: DemoPlay[] };
  return Array.isArray(body.own) ? body.own : [];
}

const DEMO_PLAY_PATH: Record<DemoPlayAction, string> = {
  simulate_arrival: "simulate-arrival",
  approve: "approve",
  capture: "capture",
  void: "void",
  refund: "refund",
};

/** One step of the demo treasurer loop on one of this browser's own pledges. */
export async function demoPlay(
  pledgeId: string,
  action: DemoPlayAction,
): Promise<{ pledge: PublicPledge; play: DemoPlay }> {
  const res = await fetch(url(`/api/escales/demo/pledges/${encodeURIComponent(pledgeId)}/${DEMO_PLAY_PATH[action]}`), {
    method: "POST",
    headers: { "X-Pledge-Key": pledgeKey(pledgeId) ?? "" },
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

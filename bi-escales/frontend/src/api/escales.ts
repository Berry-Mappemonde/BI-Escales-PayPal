import type {
  PublicPledge,
  Milestone,
  CaptainProposal,
  CaptainChatResponse,
  ScheduleResponse,
  FeatureFlags,
  FundView,
} from "./types";

function url(path: string): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
}

/** Absolute return and cancel URLs for this page. PayPal refuses a relative URL. */
export function paypalPageUrls(): { return_url: string; cancel_url: string } {
  const path = window.location.pathname || "/";
  const origin = window.location.origin;
  return {
    return_url: `${origin}${path}?paypal=return`,
    cancel_url: `${origin}${path}?paypal=cancel`,
  };
}

export function readPaypalReturn(search: string): { action: "return" | "cancel"; pledgeId: string } | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const action = params.get("paypal");
  if (action !== "return" && action !== "cancel") return null;
  return { action, pledgeId: params.get("pledge_id") || "" };
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join(", ");
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(url("/api/health"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** A cold Render start often answers 502 before the process is up. */
export const HEALTH_ATTEMPTS = 6;
export const HEALTH_WAIT_MS = 3000;

export type HealthBanner = "ok" | "wait" | "down";

/** ``null`` is still retrying. The failure text waits until the retries end. */
export function healthBanner(ok: boolean | null): HealthBanner {
  if (ok === null) return "wait";
  return ok ? "ok" : "down";
}

export async function fetchHealthRetrying(
  attempt: () => Promise<{ status: string }> = fetchHealth,
  options?: { attempts?: number; waitMs?: number; sleep?: (ms: number) => Promise<void> },
): Promise<{ status: string }> {
  const attempts = options?.attempts ?? HEALTH_ATTEMPTS;
  const waitMs = options?.waitMs ?? HEALTH_WAIT_MS;
  const sleep = options?.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  let last: unknown;
  for (let index = 0; index < attempts; index += 1) {
    try {
      return await attempt();
    } catch (err) {
      last = err;
      if (index < attempts - 1) await sleep(waitMs);
    }
  }
  throw last instanceof Error ? last : new Error(String(last ?? "health failed"));
}

export async function createPledge(
  body: {
    amount_eur: string;
    description: string;
    milestone_id: string;
    contributor?: string;
    kind?: string;
    target_id?: string;
  },
  paypalRequestId: string,
): Promise<PublicPledge> {
  const res = await fetch(url("/api/escales/pledges"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PayPal-Request-Id": paypalRequestId,
    },
    body: JSON.stringify({ ...paypalPageUrls(), ...body }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function authorizePledge(pledgeId: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/authorize`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listPledges(adminKey: string): Promise<PublicPledge[]> {
  const res = await fetch(url("/api/escales/pledges"), {
    headers: { "x-admin-key": adminKey },
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function registerVault(pledgeId: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/vault`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchSchedule(): Promise<ScheduleResponse> {
  const res = await fetch(url("/api/escales/schedule"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchFeatures(): Promise<FeatureFlags> {
  const res = await fetch(url("/api/escales/features"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export function isVaultPledge(pledge: PublicPledge): boolean {
  if (pledge.payment_mode === "VAULT" || pledge.intent === "VAULT") return true;
  return Boolean(pledge.setup_token_id && !pledge.order_id);
}

export async function getPledge(pledgeId: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}`));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function capturePledge(pledgeId: string, adminKey: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/capture`), {
    method: "POST",
    headers: { "x-admin-key": adminKey },
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function voidPledge(pledgeId: string, adminKey: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/void`), {
    method: "POST",
    headers: { "x-admin-key": adminKey },
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function recordSpending(
  milestoneId: string,
  body: { amount_eur: string; description: string },
  adminKey: string,
): Promise<FundView> {
  const res = await fetch(url(`/api/escales/milestones/${encodeURIComponent(milestoneId)}/fund/spending`), {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-admin-key": adminKey },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchFund(milestoneId: string, adminKey?: string): Promise<FundView> {
  const headers: Record<string, string> = {};
  const key = (adminKey || "").trim();
  if (key) headers["x-admin-key"] = key;
  const res = await fetch(url(`/api/escales/milestones/${encodeURIComponent(milestoneId)}/fund`), { headers });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listMilestones(): Promise<Milestone[]> {
  const res = await fetch(url("/api/escales/milestones"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function postEvidence(
  milestoneId: string,
  body: { met?: boolean; facts?: Record<string, unknown> },
): Promise<Record<string, unknown>> {
  const res = await fetch(url(`/api/escales/milestones/${encodeURIComponent(milestoneId)}/evidence`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function captainReview(milestoneId: string, adminKey?: string): Promise<CaptainProposal> {
  const headers: Record<string, string> = {};
  const key = (adminKey || "").trim();
  if (key) headers["x-admin-key"] = key;
  const res = await fetch(url(`/api/escales/captain/review/${encodeURIComponent(milestoneId)}`), {
    method: "POST",
    headers,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function captainChat(message: string, lang?: string): Promise<CaptainChatResponse> {
  const body: { message: string; lang?: string } = { message };
  if (lang === "fr" || lang === "en") body.lang = lang;
  const res = await fetch(url("/api/escales/captain/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

import type {
  PublicPledge,
  Milestone,
  CaptainProposal,
  CaptainChatResponse,
  ScheduleResponse,
  FeatureFlags,
} from "./types";

function url(path: string): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
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
    body: JSON.stringify(body),
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

export async function captainReview(milestoneId: string): Promise<CaptainProposal> {
  const res = await fetch(url(`/api/escales/captain/review/${encodeURIComponent(milestoneId)}`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function captainChat(message: string): Promise<CaptainChatResponse> {
  const res = await fetch(url("/api/escales/captain/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

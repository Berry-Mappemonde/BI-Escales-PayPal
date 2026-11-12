import type {
  PublicPledge,
  Milestone,
  CaptainProposal,
  CaptainChatResponse,
  ScheduleResponse,
  PriceCatalog,
  FeatureFlags,
  FundView,
  PublicProjectDonationTotal,
  ClockSettleResponse,
  TreasurerAccessOptions,
  Channel3CatalogItem,
  PublicWishlist,
  TreasurerWishlistDoc,
} from "./types";
import { rememberPledgeKey } from "../demo/ownPledges";
import { captainSessionHeaders } from "./escalesSession";

function treasurerAccessHeaders(
  adminKey: string,
  access?: TreasurerAccessOptions,
): Record<string, string> {
  const key = adminKey.trim();
  if (key) {
    // A key always wins: money routes refuse a keyless demo session.
    return { "x-admin-key": key };
  }
  if (access?.demoTreasurer) {
    return {};
  }
  throw new Error("Admin key required");
}

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

/** PayPal subscription redirect return/cancel (server default uses ?sub=). */
export function crewSubscriptionPageUrls(): { return_url: string; cancel_url: string } {
  const path = window.location.pathname || "/";
  const origin = window.location.origin;
  return {
    return_url: `${origin}${path}?sub=return`,
    cancel_url: `${origin}${path}?sub=cancel`,
  };
}

export function readCrewSubscribeReturn(
  search: string,
  hash: string,
): { action: "return" | "cancel"; subscriptionId?: string } | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const sub = params.get("sub");
  if (sub === "return" || sub === "cancel") {
    const subscriptionId =
      params.get("subscription_id") || params.get("ba_token") || params.get("token") || undefined;
    return { action: sub, subscriptionId: subscriptionId || undefined };
  }
  const hashBody = (hash || "").replace(/^#/, "");
  if (hashBody === "crew-subscribe=return") return { action: "return" };
  if (hashBody === "crew-subscribe=cancel") return { action: "cancel" };
  return null;
}

export function readPaypalReturn(search: string): { action: "return" | "cancel"; pledgeId: string } | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const action = params.get("paypal");
  if (action !== "return" && action !== "cancel") return null;
  return { action, pledgeId: params.get("pledge_id") || "" };
}

export function readVaultReturn(
  search: string,
): { action: "return" | "cancel"; pledgeId: string; approvalTokenId?: string } | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const action = params.get("vault");
  if (action !== "return" && action !== "cancel") return null;
  const approvalTokenId =
    params.get("approval_token_id") || params.get("approval_session_id") || params.get("token") || undefined;
  return {
    action,
    pledgeId: params.get("pledge_id") || "",
    approvalTokenId: approvalTokenId || undefined,
  };
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

async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(url("/api/health"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** A cold Render start often answers 502 before the process is up. */
const HEALTH_ATTEMPTS = 6;
const HEALTH_WAIT_MS = 3000;

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

export async function fetchPledgeMode(milestoneId: string, kind = "mile"): Promise<{ payment_mode: "AUTHORIZE" | "VAULT" | "CAPTURE" }> {
  const params = new URLSearchParams({ milestone_id: milestoneId, kind });
  const res = await fetch(url(`/api/escales/pledges/mode?${params}`));
  if (!res.ok) throw new Error(await parseError(res));
  const body = await res.json();
  if (!["AUTHORIZE", "VAULT", "CAPTURE"].includes(body.payment_mode)) throw new Error("Invalid card payment mode");
  return body;
}

export async function createPledge(
  body: {
    quantity?: number;
    amount_eur: string;
    description: string;
    milestone_id: string;
    contributor?: string;
    kind?: string;
    target_id?: string;
    checkout_method?: "wallet" | "card";
    lang?: string;
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
  const pledge = (await res.json()) as PublicPledge;
  // The demo treasurer lets a visitor act on the pledges their own browser made. The
  // request id above is the proof; remembered here, checked by the server each time.
  rememberPledgeKey(pledge?.id, paypalRequestId);
  return pledge;
}

export async function authorizePledge(pledgeId: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/authorize`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** Public status read used to resolve an uncertain capture response. */
export async function fetchPledgeStatus(pledgeId: string): Promise<{ status: PublicPledge["status"] }> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}`));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type MileCertificateLinks = {
  token: string;
  mile_number: number;
  mile_quantity: number;
  issue_date: string;
  png: string;
  pdf: string;
};

export function mileCertificatePayerProof(pledge: PublicPledge): string | null {
  const vault = pledge.payment_mode === "VAULT" || pledge.intent === "VAULT";
  if (vault) {
    const setup = pledge.setup_token_id?.trim();
    return setup || null;
  }
  const order = pledge.order_id?.trim();
  return order || null;
}

export async function issueMileCertificate(
  pledgeId: string,
  payerProof: string,
  displayName?: string,
  lang?: string,
): Promise<MileCertificateLinks> {
  const query = lang ? `?lang=${encodeURIComponent(lang)}` : "";
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/certificate${query}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      payer_proof: payerProof,
      ...(displayName ? { display_name: displayName } : {}),
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export function certificateAssetUrl(token: string, fmt: "png" | "pdf", lang?: string): string {
  const suffix = lang ? `?lang=${encodeURIComponent(lang)}` : "";
  return url(`/api/escales/certificates/${encodeURIComponent(token)}.${fmt}${suffix}`);
}

export async function listPledges(
  adminKey: string,
  access?: TreasurerAccessOptions,
): Promise<PublicPledge[]> {
  const res = await fetch(url("/api/escales/pledges"), {
    headers: treasurerAccessHeaders(adminKey, access),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function registerVault(pledgeId: string, setupTokenId?: string): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/vault`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ setup_token_id: setupTokenId || undefined }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchSchedule(): Promise<ScheduleResponse> {
  const res = await fetch(url("/api/escales/schedule"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** Public simulated price catalogue (`GET /api/escales/prices`). Sends `lang` like other escales reads. */
export async function fetchPrices(lang?: string): Promise<PriceCatalog> {
  const params = new URLSearchParams();
  const appLang = String(lang || "").trim();
  if (appLang) params.set("lang", appLang);
  const qs = params.toString();
  const res = await fetch(url(`/api/escales/prices${qs ? `?${qs}` : ""}`));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** Public voyage clock. ``now`` is the simulated instant, real UTC unless pinned. */
/** A sleeping host can hold a request for most of a minute; the clock gives up before that. */
export const CLOCK_TIMEOUT_MS = 12000;

export async function fetchClock(timeoutMs = CLOCK_TIMEOUT_MS): Promise<{ start?: string; now?: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url("/api/escales/clock"), { signal: controller.signal });
    if (!res.ok) throw new Error(await parseError(res));
    return await res.json();
  } catch (err) {
    if (controller.signal.aborted) throw new Error(`Clock request timed out after ${timeoutMs} ms`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
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

export async function settleClock(adminKey: string, now?: string): Promise<ClockSettleResponse> {
  const key = adminKey.trim();
  if (!key) {
    throw new Error("treasurer key required");
  }
  const at = (now || "").trim();
  const body = at ? { now: at } : {};
  const res = await fetch(url("/api/escales/clock/settle"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-admin-key": key },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function capturePledge(
  pledgeId: string,
  adminKey: string,
  access?: TreasurerAccessOptions,
): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/capture`), {
    method: "POST",
    headers: treasurerAccessHeaders(adminKey, access),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function voidPledge(
  pledgeId: string,
  adminKey: string,
  access?: TreasurerAccessOptions,
): Promise<PublicPledge> {
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/void`), {
    method: "POST",
    headers: treasurerAccessHeaders(adminKey, access),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function refundPledge(
  pledgeId: string,
  adminKey: string,
  amountEur?: string,
  access?: TreasurerAccessOptions,
): Promise<PublicPledge> {
  const body = amountEur?.trim() ? { amount_eur: amountEur.trim() } : {};
  const res = await fetch(url(`/api/escales/pledges/${encodeURIComponent(pledgeId)}/refund`), {
    method: "POST",
    headers: { ...treasurerAccessHeaders(adminKey, access), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface WebhookOutcomeRow {
  transmission_id?: string;
  event_type?: string | null;
  resource_id?: string | null;
  pledge_id?: string | null;
  time?: string;
  outcome?: string;
}

export async function fetchRecentWebhooks(adminKey: string): Promise<WebhookOutcomeRow[]> {
  const res = await fetch(url("/api/escales/webhooks/recent"), {
    headers: { "x-admin-key": adminKey.trim() },
  });
  if (!res.ok) throw new Error(await parseError(res));
  const body = (await res.json()) as { events?: WebhookOutcomeRow[] };
  return Array.isArray(body.events) ? body.events : [];
}

export async function approveCaptainReview(
  milestoneId: string,
  adminKey: string,
  access?: TreasurerAccessOptions,
): Promise<{ milestone_id: string; approved: boolean }> {
  const res = await fetch(
    url(`/api/escales/milestones/${encodeURIComponent(milestoneId)}/captain-review/approve`),
    {
      method: "POST",
      headers: treasurerAccessHeaders(adminKey, access),
    },
  );
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

/** Public GET /gear — expedition Gear features (seed + optional Channel3). */
export interface GearFeatureCollection {
  type: "FeatureCollection";
  name?: string;
  source?: string;
  features: Array<{
    type: "Feature";
    geometry?: { type: string; coordinates?: number[] };
    properties?: Record<string, unknown>;
  }>;
}

export async function fetchGearProjects(): Promise<GearFeatureCollection | null> {
  try {
    const res = await fetch(url("/api/escales/gear"));
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/** Public expedition cart (six gear lines + voyage marinas). */
export async function fetchExpeditionCart(lang?: string): Promise<{
  lines?: Array<{
    kind?: string;
    id?: string;
    description?: string;
    amount_eur?: string | null;
    currency?: string;
    price_label?: string | null;
  }>;
  gear_count?: number;
  marina_count?: number;
}> {
  const qs = lang?.trim() ? `?lang=${encodeURIComponent(lang.trim())}` : "";
  const res = await fetch(url(`/api/escales/expedition/cart${qs}`));
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

/** Public project crowdfunding totals (pattern: ``fetchFund`` without admin key). */
export async function fetchPublicProjectFund(projectId: string): Promise<PublicProjectDonationTotal | null> {
  const id = String(projectId || "").trim();
  if (!id) return null;
  try {
    const res = await fetch(url(`/api/escales/projects/${encodeURIComponent(id)}/fund`));
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/** Public GET /common-fund/fund (N36). Boat common-fund totals only. */
export async function fetchPublicCommonFund(): Promise<FundView | null> {
  try {
    const res = await fetch(url("/api/escales/common-fund/fund"));
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/** One stopover or cabin-leg row of GET /funds/public. Amounts only. */
export interface PublicFundRow {
  milestone_id: string;
  fund_id: string;
  authorized_eur: string;
  captured_eur: string;
  refunded_eur: string;
}

export interface PublicProjectRow {
  project_id: string;
  amount_eur: string;
  donation_count: number;
  refunded_eur: string;
}

export interface PublicFunds {
  currency: string;
  stops: PublicFundRow[];
  legs: PublicFundRow[];
  projects: PublicProjectRow[];
  common_fund: { authorized_eur: string; captured_eur: string; refunded_eur: string };
  truncated?: boolean;
}

/** Public GET /funds/public: every public total in one read. Throws when it cannot be read. */
export async function fetchPublicFunds(): Promise<PublicFunds> {
  const res = await fetch(url("/api/escales/funds/public"));
  if (!res.ok) throw new Error(await parseError(res));
  const body = await res.json();
  // An answer of another shape (an older API, a proxy page) is "not available", not a crash.
  if (!body || !Array.isArray(body.stops) || !Array.isArray(body.legs) || !Array.isArray(body.projects)) {
    throw new Error("Unexpected public funds answer");
  }
  return { ...body, common_fund: body.common_fund ?? { authorized_eur: "0.00", captured_eur: "0.00", refunded_eur: "0.00" } };
}

export interface DemoStopAction {
  pledge_id: string;
  action: string;
  status?: string;
  capture_id?: string;
  void_id?: string;
  detail?: string;
}

export interface DemoStopMomentResponse {
  milestone_id: string;
  now?: string;
  demo_cancelled?: boolean;
  captain_review_approved_at?: string;
  actions: DemoStopAction[];
}

async function postDemoStop(
  action: string,
  milestoneId: string,
  adminKey: string,
): Promise<DemoStopMomentResponse> {
  const res = await fetch(
    url(`/api/escales/demo/stops/${encodeURIComponent(milestoneId)}/${action}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-key": adminKey.trim() },
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export function demoSimulateArrival(milestoneId: string, adminKey: string): Promise<DemoStopMomentResponse> {
  return postDemoStop("simulate-arrival", milestoneId, adminKey);
}

export function demoCancelStop(milestoneId: string, adminKey: string): Promise<DemoStopMomentResponse> {
  return postDemoStop("cancel", milestoneId, adminKey);
}

export function demoResetStop(milestoneId: string, adminKey: string): Promise<DemoStopMomentResponse> {
  return postDemoStop("reset", milestoneId, adminKey);
}

export async function listMilestones(): Promise<Milestone[]> {
  const res = await fetch(url("/api/escales/milestones"));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function captainReview(
  milestoneId: string,
  adminKey?: string,
  lang?: string,
  access?: TreasurerAccessOptions,
): Promise<CaptainProposal> {
  const headers: Record<string, string> = {};
  if (access?.demoTreasurer) {
    /* demo session: no x-admin-key */
  } else {
    const key = (adminKey || "").trim();
    if (key) headers["x-admin-key"] = key;
  }
  const params = new URLSearchParams();
  if (lang === "fr" || lang === "en") params.set("lang", lang);
  const qs = params.toString();
  const res = await fetch(
    url(`/api/escales/captain/review/${encodeURIComponent(milestoneId)}${qs ? `?${qs}` : ""}`),
    {
      method: "POST",
      headers: { ...headers, ...captainSessionHeaders() },
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function captainChat(
  message: string,
  lang?: string,
  adminKey?: string,
): Promise<CaptainChatResponse> {
  const body: { message: string; lang?: string } = { message };
  if (lang === "fr" || lang === "en") body.lang = lang;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = (adminKey || "").trim();
  if (key) headers["x-admin-key"] = key;
  const res = await fetch(url("/api/escales/captain/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers, ...captainSessionHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

function treasurerHeaders(adminKey: string): Record<string, string> {
  return { "x-admin-key": adminKey.trim() };
}

export async function fetchPayPalDisputes(adminKey: string): Promise<{
  paypal: { items?: unknown[] };
  snapshots?: unknown[];
}> {
  const res = await fetch(url("/api/escales/paypal/disputes"), { headers: treasurerHeaders(adminKey) });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchPayPalInvoices(adminKey: string): Promise<{ paypal: { items?: unknown[] } }> {
  const res = await fetch(url("/api/escales/paypal/invoices"), { headers: treasurerHeaders(adminKey) });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function createPayPalInvoice(
  adminKey: string,
  body: { recipient_email: string; amount_eur: string; description: string; reference?: string; lang?: string },
): Promise<Record<string, unknown>> {
  const res = await fetch(url("/api/escales/paypal/invoices"), {
    method: "POST",
    headers: { ...treasurerHeaders(adminKey), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchPayPalSubscriptions(adminKey: string): Promise<{ items: unknown[] }> {
  const res = await fetch(url("/api/escales/paypal/subscriptions"), { headers: treasurerHeaders(adminKey) });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function setupCrewSubscription(adminKey: string): Promise<{
  product_id?: string;
  plan_id?: string;
  idempotent?: boolean;
}> {
  const res = await fetch(url("/api/escales/paypal/subscriptions/setup"), {
    method: "POST",
    headers: treasurerHeaders(adminKey),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchCrewSupporterPlan(lang?: string): Promise<{ plan_id: string | null; lang?: string }> {
  const params = new URLSearchParams();
  if (lang?.trim()) params.set("lang", lang.trim());
  const qs = params.toString();
  const res = await fetch(url(`/api/escales/paypal/subscriptions/plan${qs ? `?${qs}` : ""}`));
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function approveCrewSubscription(body: {
  subscription_id: string;
  plan_id: string;
}): Promise<Record<string, unknown>> {
  const res = await fetch(url("/api/escales/paypal/subscriptions/approve"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function recordSubscription(
  adminKey: string,
  body: { subscription_id: string; plan_id: string; status?: string; subscriber_email?: string },
): Promise<Record<string, unknown>> {
  const res = await fetch(url("/api/escales/paypal/subscriptions/record"), {
    method: "POST",
    headers: { ...treasurerHeaders(adminKey), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** GET /channel3/catalog — public seed catalogue + funding fields. */
export async function fetchChannel3Catalog(): Promise<{ item_count: number; items: Channel3CatalogItem[] }> {
  const res = await fetch(url("/api/escales/channel3/catalog"));
  if (!res.ok) throw new Error(await parseError(res));
  const body = (await res.json()) as { item_count?: number; items?: Channel3CatalogItem[] };
  return {
    item_count: Number(body.item_count) || 0,
    items: Array.isArray(body.items) ? body.items : [],
  };
}

/** GET /wishlists — published wishlists only. */
export async function fetchPublicWishlists(): Promise<{ wishlists: PublicWishlist[] }> {
  const res = await fetch(url("/api/escales/wishlists"));
  if (!res.ok) throw new Error(await parseError(res));
  const body = (await res.json()) as { wishlists?: PublicWishlist[] };
  return { wishlists: Array.isArray(body.wishlists) ? body.wishlists : [] };
}

export async function fetchTreasurerWishlists(adminKey: string): Promise<{ wishlists: TreasurerWishlistDoc[] }> {
  const res = await fetch(url("/api/escales/treasurer/wishlists"), {
    headers: treasurerHeaders(adminKey),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const body = (await res.json()) as { wishlists?: TreasurerWishlistDoc[] };
  return { wishlists: Array.isArray(body.wishlists) ? body.wishlists : [] };
}

export async function createTreasurerWishlist(
  adminKey: string,
  body: { title: string; slug: string; items?: Array<{ channel3_product_id: string; quantity?: number; target_amount_minor?: number | null; allow_optional?: boolean }> },
): Promise<TreasurerWishlistDoc> {
  const res = await fetch(url("/api/escales/treasurer/wishlists"), {
    method: "POST",
    headers: { ...treasurerHeaders(adminKey), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function addTreasurerWishlistItem(
  adminKey: string,
  wishlistId: string,
  body: { channel3_product_id: string; quantity?: number; target_amount_minor?: number | null; allow_optional?: boolean },
): Promise<TreasurerWishlistDoc> {
  const res = await fetch(url(`/api/escales/treasurer/wishlists/${encodeURIComponent(wishlistId)}/items`), {
    method: "POST",
    headers: { ...treasurerHeaders(adminKey), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function removeTreasurerWishlistItem(
  adminKey: string,
  wishlistId: string,
  channel3ProductId: string,
): Promise<TreasurerWishlistDoc> {
  const res = await fetch(
    url(
      `/api/escales/treasurer/wishlists/${encodeURIComponent(wishlistId)}/items/${encodeURIComponent(channel3ProductId)}`,
    ),
    { method: "DELETE", headers: treasurerHeaders(adminKey) },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function publishTreasurerWishlist(
  adminKey: string,
  wishlistId: string,
  published: boolean,
): Promise<TreasurerWishlistDoc> {
  const res = await fetch(url(`/api/escales/treasurer/wishlists/${encodeURIComponent(wishlistId)}/publish`), {
    method: "POST",
    headers: { ...treasurerHeaders(adminKey), "Content-Type": "application/json" },
    body: JSON.stringify({ published }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

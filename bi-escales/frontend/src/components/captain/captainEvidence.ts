import type { CaptainProposal, PublicPledge, ScheduleResponse } from "../../api/types";

export type SourceKind = "schedule" | "pending_authorizations" | "authorizations.get" | "orders.get";

export interface CaptainSource {
  n: number;
  kind: SourceKind;
  /** PayPal resource ids read for this source. Empty for non-PayPal sources. */
  ids: string[];
}

export type ClaimKey = "arrival" | "holds" | "validTo" | "expired" | "authorizationsRead" | "ordersRead";

export interface CaptainClaim {
  key: ClaimKey;
  /** The source number this claim rests on. */
  cite: number;
  iso?: string;
  count?: number;
  totalEur?: number;
}

export interface StopOnSchedule {
  name?: string;
  arrivalIso?: string;
}

/** Sums euro strings in whole cents, so 0.1 + 0.2 stays 0.30. */
export function sumEur(amounts: (string | undefined)[]): number {
  const cents = amounts.reduce((total, amount) => {
    const value = Number(String(amount ?? "").replace(",", "."));
    return Number.isFinite(value) ? total + Math.round(value * 100) : total;
  }, 0);
  return cents / 100;
}

export function stopOnSchedule(schedule: ScheduleResponse | null, milestoneId: string): StopOnSchedule {
  const rows = [...(schedule?.export?.escales ?? []), ...(schedule?.milestones ?? [])];
  const row = rows.find((item) => item.milestone_id === milestoneId);
  if (row) {
    return { name: row.name || row.title, arrivalIso: row.arrival_iso || undefined };
  }
  const leg = schedule?.legs?.find((item) => item.id === milestoneId);
  if (leg) {
    const name = leg.from_name && leg.to_name ? `${leg.from_name} → ${leg.to_name}` : undefined;
    return { name, arrivalIso: leg.arrival_iso || undefined };
  }
  return {};
}

function earliest(isoDates: (string | null | undefined)[]): string | undefined {
  const known = isoDates.filter((iso): iso is string => Boolean(iso) && !Number.isNaN(Date.parse(String(iso))));
  return known.sort((a, b) => Date.parse(a) - Date.parse(b))[0];
}

function toolIds(review: CaptainProposal | null, tool: string): string[] {
  const ids = (review?.paypal_tool_calls ?? [])
    .filter((call) => call.tool === tool && call.resource_id)
    .map((call) => String(call.resource_id));
  return [...new Set(ids)];
}

/**
 * Every claim comes from a structured field and cites where it came from. A
 * missing field drops the claim and its source, so nothing is ever implied.
 * A tool call only proves PayPal was read, not what it answered, so those
 * claims say "read" and never repeat a status.
 */
export function buildEvidence(
  review: CaptainProposal | null,
  arrivalIso: string | undefined,
  now: Date = new Date(),
): { claims: CaptainClaim[]; sources: CaptainSource[] } {
  const claims: CaptainClaim[] = [];
  const sources: CaptainSource[] = [];
  const addSource = (kind: SourceKind, ids: string[] = []) => {
    const n = sources.length + 1;
    sources.push({ n, kind, ids });
    return n;
  };

  if (arrivalIso) {
    claims.push({ key: "arrival", cite: addSource("schedule"), iso: arrivalIso });
  }

  const pending = review?.pending_authorizations ?? [];
  if (pending.length) {
    const cite = addSource("pending_authorizations");
    claims.push({
      key: "holds",
      cite,
      count: pending.length,
      totalEur: sumEur(pending.map((row) => row.amount_eur)),
    });
    const expiry = earliest(pending.map((row) => row.authorization_expires_at));
    if (expiry) {
      claims.push({ key: Date.parse(expiry) < now.getTime() ? "expired" : "validTo", cite, iso: expiry });
    }
  }

  const authorizations = toolIds(review, "authorizations.get");
  if (authorizations.length) {
    claims.push({
      key: "authorizationsRead",
      cite: addSource("authorizations.get", authorizations),
      count: authorizations.length,
    });
  }

  const orders = toolIds(review, "orders.get");
  if (orders.length) {
    claims.push({ key: "ordersRead", cite: addSource("orders.get", orders), count: orders.length });
  }

  return { claims, sources };
}

/** The pledges Override can release: the void route accepts these two states only. */
export function releasableHolds(pledges: PublicPledge[], milestoneId: string): PublicPledge[] {
  return pledges.filter(
    (pledge) =>
      pledge.milestone_id === milestoneId && (pledge.status === "authorized" || pledge.status === "vaulted"),
  );
}

export type ModelLabel =
  | { kind: "model"; model: string; provider: string }
  | { kind: "provider"; provider: string }
  | { kind: "model_unnamed" }
  | { kind: "rules" };

const PROVIDER_NAMES: Record<string, string> = { nim: "NVIDIA NIM", nim_fallback: "NVIDIA NIM" };

function modelName(model: string): string {
  if (/nemotron/i.test(model)) return "Nemotron";
  return model.split("/").pop() || model;
}

/** Who wrote the report. A rules fallback must never read as a model answer. */
export function describeModelSource(source: CaptainProposal["model_source"]): ModelLabel | null {
  if (!source) return null;
  const provider = String(source.provider ?? "").trim().toLowerCase();
  const model = String(source.model ?? "").trim();
  if (provider === "rules" || provider === "none") return { kind: "rules" };
  const providerName = PROVIDER_NAMES[provider];
  if (model && providerName) return { kind: "model", model: modelName(model), provider: providerName };
  if (model) return { kind: "provider", provider: modelName(model) };
  if (providerName) return { kind: "provider", provider: providerName };
  return provider ? { kind: "model_unnamed" } : null;
}

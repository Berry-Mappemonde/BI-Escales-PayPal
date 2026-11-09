import type { PublicPledge, PledgeGaugeRow } from "../api/types";

export interface MarinaDashboardRow {
  marina_key: string;
  berth_bookings: number;
  gross_eur: number;
  platform_fees_eur: number;
  marina_net_eur: number;
  refunds_eur: number;
  disputes_open: number;
  fees_simulated: boolean;
  marina_payout_status: string;
}

function summarizeMarinaPayoutStatus(pledges: PublicPledge[]): string {
  const statuses = pledges
    .filter((p) => isCapturedBerth(p))
    .map((p) => String(p.marina_payout_status || "").trim().toLowerCase())
    .filter(Boolean);
  if (statuses.length === 0) return "—";
  if (statuses.some((s) => s === "denied" || s === "failed")) return "denied";
  if (statuses.some((s) => s === "pending" || s === "processing" || s === "sent")) return "processing";
  if (statuses.every((s) => s === "success")) return "success";
  if (statuses.some((s) => s === "pending_email")) return "pending_email";
  return statuses[0];
}

const CAPTURED_STATUSES = new Set<PublicPledge["status"]>([
  "captured",
  "partially_refunded",
  "refunded",
]);

function parseEur(value: string | null | undefined): number {
  const n = parseFloat(value || "0");
  return Number.isFinite(n) ? n : 0;
}

/** Ledger pledges stay EUR in sandbox; skip other currencies so totals never mix FX. */
function isEurPledge(p: PublicPledge): boolean {
  const code = String(p.currency || "EUR").trim().toUpperCase();
  return code === "EUR" || code === "EURO";
}

function isCapturedBerth(p: PublicPledge): boolean {
  return (p.kind || "") === "berth" && CAPTURED_STATUSES.has(p.status);
}

export function sumAmount(pledges: PublicPledge[], status: PublicPledge["status"]): number {
  return pledges
    .filter((p) => p.status === status && isEurPledge(p))
    .reduce((acc, p) => acc + parseEur(p.amount_eur), 0);
}

export function countByStatus(pledges: PublicPledge[], status: PublicPledge["status"]): number {
  return pledges.filter((p) => p.status === status).length;
}

export function buildGaugeRows(pledges: PublicPledge[]): PledgeGaugeRow[] {
  const byMilestone = new Map<string, PublicPledge[]>();
  for (const p of pledges) {
    const list = byMilestone.get(p.milestone_id) ?? [];
    list.push(p);
    byMilestone.set(p.milestone_id, list);
  }
  return [...byMilestone.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([milestone_id, list]) => ({
      milestone_id,
      authorized_count: countByStatus(list, "authorized"),
      authorized_total_eur: sumAmount(list, "authorized"),
      captured_count: countByStatus(list, "captured"),
      captured_total_eur: sumAmount(list, "captured"),
      voided_count: countByStatus(list, "voided"),
    }));
}

export function gaugePercent(row: PledgeGaugeRow, field: "authorized" | "captured" | "voided"): number {
  const total =
    row.authorized_count + row.captured_count + row.voided_count;
  if (total === 0) return 0;
  if (field === "authorized") return Math.round((row.authorized_count / total) * 100);
  if (field === "captured") return Math.round((row.captured_count / total) * 100);
  return Math.round((row.voided_count / total) * 100);
}

/** Marina berth dashboard from ledger-backed fee fields on captured pledges. */
export function buildMarinaDashboardRows(pledges: PublicPledge[]): MarinaDashboardRow[] {
  const byStop = new Map<string, PublicPledge[]>();
  for (const p of pledges) {
    if ((p.kind || "") !== "berth") continue;
    const key = (p.milestone_id || p.target_id || "—").trim() || "—";
    const list = byStop.get(key) ?? [];
    list.push(p);
    byStop.set(key, list);
  }
  return [...byStop.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([marina_key, list]) => {
      const eurRows = list.filter((row) => isEurPledge(row));
      const gross = eurRows.reduce((acc, row) => acc + parseEur(row.amount_eur), 0);
      const refunds = eurRows
        .filter((row) => row.status === "refunded" || row.status === "partially_refunded")
        .reduce((acc, row) => acc + parseEur(row.amount_eur), 0);
      const captured = eurRows.filter((row) => isCapturedBerth(row));
      const platform_fees_eur = captured.reduce(
        (acc, row) => acc + parseEur(row.platform_fee_eur),
        0,
      );
      const marina_net_eur = captured.reduce((acc, row) => acc + parseEur(row.marina_net_eur), 0);
      const fees_simulated = captured.some((row) => row.platform_fee_simulated === true);
      const marina_payout_status = summarizeMarinaPayoutStatus(list);
      return {
        marina_key,
        berth_bookings: list.length,
        gross_eur: gross,
        platform_fees_eur,
        marina_net_eur,
        refunds_eur: refunds,
        disputes_open: 0,
        fees_simulated,
        marina_payout_status,
      };
    });
}

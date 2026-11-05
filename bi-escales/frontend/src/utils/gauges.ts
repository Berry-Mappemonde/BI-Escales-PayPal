import type { PublicPledge, PledgeGaugeRow } from "../api/types";

export interface MarinaDashboardRow {
  marina_key: string;
  berth_bookings: number;
  gross_eur: number;
  platform_fees_eur: number;
  refunds_eur: number;
  disputes_open: number;
}

export function sumAmount(pledges: PublicPledge[], status: PublicPledge["status"]): number {
  return pledges
    .filter((p) => p.status === status)
    .reduce((acc, p) => acc + parseFloat(p.amount_eur || "0"), 0);
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

const PLATFORM_FEE_PER_BERTH = 3;

/** Marina berth dashboard: bookings, gross, fee estimate, refunds (disputes placeholder). */
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
      const gross = list.reduce((acc, row) => acc + parseFloat(row.amount_eur || "0"), 0);
      const refunds = list
        .filter((row) => row.status === "refunded" || row.status === "partially_refunded")
        .reduce((acc, row) => acc + parseFloat(row.amount_eur || "0"), 0);
      const capturedOrAuth = list.filter((row) =>
        ["authorized", "captured", "settled", "pending"].includes(row.status),
      ).length;
      return {
        marina_key,
        berth_bookings: list.length,
        gross_eur: gross,
        platform_fees_eur: capturedOrAuth * PLATFORM_FEE_PER_BERTH,
        refunds_eur: refunds,
        disputes_open: 0,
      };
    });
}

import type { PublicPledge, PledgeGaugeRow } from "../api/types";

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

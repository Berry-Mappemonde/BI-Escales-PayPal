import type { PublicPledge } from "../api/types";

export const fundingTypes = ["stop", "leg", "common", "project", "unassigned"] as const;
export type FundingType = typeof fundingTypes[number];

export interface LedgerPledge {
  id: string;
  status: string;
  type: FundingType;
  target: string;
  currency: string;
  pledged: number | null;
  captured: number | null;
  refunded: number | null;
  authorized: number | null;
  vaulted: number | null;
  voided: number | null;
}

// The ledger stores decimal strings, including two decimal places for supported currencies.
function cents(raw?: string): number | null {
  if (!raw || !/^\d+(\.\d{1,2})?$/.test(raw)) return null;
  const [whole, fraction = ""] = raw.split(".");
  const result = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(result) ? result : null;
}

function destination(pledge: PublicPledge): Pick<LedgerPledge, "type" | "target"> {
  const milestone = pledge.milestone_id?.trim() ?? "";
  const target = pledge.target_id?.trim() ?? "";
  if (pledge.kind === "project_pledge") return { type: "project", target: target || milestone };
  if (pledge.kind === "common_fund") return { type: "common", target: "fonds-commun" };
  if (pledge.kind === "cabin_leg" || milestone.startsWith("leg-") || target.startsWith("leg-")) {
    return { type: "leg", target: milestone.startsWith("leg-") ? milestone : target || milestone };
  }
  return { type: milestone ? "stop" : "unassigned", target: milestone };
}

/** Allowlist dashboard fields before storing a response, including when switching to demo. */
export function ledgerPledges(pledges: PublicPledge[]): LedgerPledge[] {
  return pledges.map((pledge) => {
    const { status } = pledge;
    const pledged = cents(pledge.amount_eur);
    const refunded = status === "refunded"
      ? cents(pledge.refunded_amount_eur) ?? pledged
      : status === "partially_refunded" ? cents(pledge.refunded_amount_eur) : 0;
    return {
      id: pledge.id,
      status,
      ...destination(pledge),
      currency: pledge.currency?.trim().toUpperCase() || "EUR",
      pledged,
      captured: status === "captured" ? pledged
        : status === "partially_refunded"
          ? pledged !== null && refunded !== null && refunded <= pledged ? pledged - refunded : null
          : 0,
      refunded: pledged !== null && refunded !== null && refunded > pledged ? null : refunded,
      authorized: status === "authorized" ? pledged : 0,
      vaulted: status === "vaulted" ? pledged : 0,
      voided: status === "voided" ? pledged : 0,
    };
  });
}

export const totalFields = ["captured", "authorized", "vaulted", "voided", "refunded"] as const;
export type TotalField = typeof totalFields[number];
export type LedgerTotals = Pick<LedgerPledge, TotalField> & { count: number };

export function ledgerTotals(rows: LedgerPledge[]): LedgerTotals {
  const totals: LedgerTotals = { count: rows.length, captured: 0, authorized: 0, vaulted: 0, voided: 0, refunded: 0 };
  for (const row of rows) {
    for (const field of totalFields) {
      const amount = row[field];
      const total = totals[field];
      totals[field] = amount === null || total === null ? null : total + amount;
    }
  }
  return totals;
}

export type GroupBy = "target" | "status" | "type";
export type LedgerGroup = LedgerTotals & { id: string; label: string; type?: FundingType };

export function groupLedger(
  rows: LedgerPledge[],
  groupBy: GroupBy,
  labelFor: (row: LedgerPledge) => string,
): LedgerGroup[] {
  const groups = new Map<string, LedgerPledge[]>();
  for (const row of rows) {
    const id = groupBy === "target" ? JSON.stringify([row.type, row.target]) : row[groupBy];
    const members = groups.get(id);
    if (members) members.push(row);
    else groups.set(id, [row]);
  }
  return Array.from(groups, ([id, members]) => ({
    id,
    label: labelFor(members[0]),
    type: groupBy === "target" ? members[0].type : undefined,
    ...ledgerTotals(members),
  }));
}

export function dashboardMoney(value: number | null | undefined, currency: string, language: string): string {
  return value == null ? "—" : new Intl.NumberFormat(language, {
    style: "currency",
    currency: /^[A-Z]{3}$/.test(currency) ? currency : "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

import type { PublicPledge } from "../api/types";

/** The API also returns the refund total, which PublicPledge does not declare. */
type StudioPledge = PublicPledge & { refunded_amount_eur?: string | null };

export interface PledgeStudioRow {
  id: string;
  status: string;
  milestone_id: string;
  amount_eur: number;
  net_eur: number;
  contributor: string;
  description: string;
}

export function toPledgeStudioRows(pledges: StudioPledge[]): PledgeStudioRow[] {
  return pledges.map((pledge) => {
    const amount = parseAmount(pledge.amount_eur);
    return {
      id: pledge.id,
      status: pledge.status,
      milestone_id: pledge.milestone_id,
      amount_eur: amount,
      net_eur: netOfRefunds(amount, pledge.refunded_amount_eur),
      contributor: pledge.contributor ?? "",
      description: pledge.description,
    };
  });
}

export function parseAmount(raw: string | null | undefined): number {
  const value = Number.parseFloat(raw ?? "");
  return Number.isFinite(value) ? value : 0;
}

function netOfRefunds(amount: number, refunded: string | null | undefined): number {
  return Math.max(0, Number((amount - parseAmount(refunded)).toFixed(2)));
}

export interface StatusTotals {
  held: number;
  saved: number;
  captured: number;
  released: number;
}

/**
 * Which scoreboard total each status feeds. `authorized` is a hold on the buyer's
 * funds; `vaulted` is only a saved payment method, so the two stay apart.
 * `refunded` is left out on purpose: a fully refunded pledge counts 0.
 */
const TOTAL_FOR_STATUS = new Map<unknown, keyof StatusTotals>([
  ["authorized", "held"],
  ["vaulted", "saved"],
  ["captured", "captured"],
  ["partially_refunded", "captured"],
  ["voided", "released"],
]);

/** Reads flat AG Studio rows whether keys are `status` or `pledges.net_eur`. */
export function totalsFromStudioRows(rows: Record<string, unknown>[]): StatusTotals {
  const totals: StatusTotals = { held: 0, saved: 0, captured: 0, released: 0 };
  for (const row of rows) {
    const total = totalForRow(row);
    if (total) totals[total] += amountOf(row);
  }
  return totals;
}

function totalForRow(row: Record<string, unknown>): keyof StatusTotals | undefined {
  for (const value of Object.values(row)) {
    const total = TOTAL_FOR_STATUS.get(value);
    if (total) return total;
  }
  return undefined;
}

function amountOf(row: Record<string, unknown>): number {
  const entries = Object.entries(row);
  const preferred =
    entries.find(([key]) => /net/i.test(key)) ?? entries.find(([key]) => /amount|montant|eur/i.test(key));
  const candidate = preferred?.[1] ?? Object.values(row).find((value) => typeof value === "number");
  const amount = typeof candidate === "number" ? candidate : Number.parseFloat(String(candidate ?? ""));
  return Number.isFinite(amount) ? amount : 0;
}

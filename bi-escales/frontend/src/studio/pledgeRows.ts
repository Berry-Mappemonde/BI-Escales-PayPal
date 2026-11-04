import type { PublicPledge } from "../api/types";

export interface PledgeStudioRow {
  id: string;
  status: string;
  milestone_id: string;
  amount_eur: number;
  contributor: string;
  description: string;
}

const TRACKED = ["authorized", "captured", "voided"] as const;
export type TrackedStatus = (typeof TRACKED)[number];

let publishedRows: PledgeStudioRow[] = [];

export function publishStudioRows(rows: PledgeStudioRow[]): void {
  publishedRows = rows;
}

export function publishedStudioRows(): PledgeStudioRow[] {
  return publishedRows;
}

export function toPledgeStudioRows(pledges: PublicPledge[]): PledgeStudioRow[] {
  return pledges.map((pledge) => ({
    id: pledge.id,
    status: pledge.status,
    milestone_id: pledge.milestone_id,
    amount_eur: parseAmount(pledge.amount_eur),
    contributor: pledge.contributor ?? "",
    description: pledge.description,
  }));
}

export function parseAmount(raw: string | undefined): number {
  const value = Number.parseFloat(raw ?? "");
  return Number.isFinite(value) ? value : 0;
}

export interface StatusTotals {
  authorized: number;
  captured: number;
  voided: number;
}

/** Reads flat AG Studio rows whether keys are `status` or `pledges.amount_eur`. */
export function totalsFromStudioRows(rows: Record<string, unknown>[]): StatusTotals {
  const totals: StatusTotals = { authorized: 0, captured: 0, voided: 0 };
  for (const row of rows) {
    const status = trackedStatus(row);
    if (!status) continue;
    totals[status] += amountOf(row);
  }
  return totals;
}

function trackedStatus(row: Record<string, unknown>): TrackedStatus | undefined {
  for (const value of Object.values(row)) {
    if (value === "authorized" || value === "captured" || value === "voided") return value;
  }
  return undefined;
}

function amountOf(row: Record<string, unknown>): number {
  const preferred = Object.entries(row).find(([key]) => /amount|montant|eur/i.test(key));
  const candidate = preferred?.[1] ?? Object.values(row).find((value) => typeof value === "number");
  const amount = typeof candidate === "number" ? candidate : Number.parseFloat(String(candidate ?? ""));
  return Number.isFinite(amount) ? amount : 0;
}

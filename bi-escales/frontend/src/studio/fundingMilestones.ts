/** Grounded funding totals for the treasurer's AG Studio crowdfunding view.
 * No financial amounts are inferred; values come only from public ledger rows.
 */
export type FundingGroupKind = "project" | "stop" | "common";
export interface FundingGroup {
  id: string;
  kind: FundingGroupKind;
  capturedEur: number;
  authorizedEur: number;
  savedEur: number;
  releasedEur: number;
  pledgeCount: number;
}

function field(row: Record<string, unknown>, name: string): unknown {
  if (Object.prototype.hasOwnProperty.call(row, name)) return row[name];
  const key = Object.keys(row).find((k) => k.endsWith(`.${name}`) || k.endsWith(`_${name}`));
  return key ? row[key] : undefined;
}

function amount(input: unknown): number {
  if (typeof input !== "string" && typeof input !== "number") return 0;
  const value = Number(String(input).trim());
  return Number.isFinite(value) && value > 0 ? Math.round(value * 100) : 0;
}

function kindFromRow(row: Record<string, unknown>): FundingGroupKind {
  const kind = String(field(row, "kind") ?? "").toLowerCase();
  if (kind === "project_pledge" || kind === "project_donation") return "project";
  if (kind.includes("common") || kind === "fund") return "common";
  return "stop";
}

/** Deterministic cents arithmetic; vault promises are never counted as captured. */
export function fundingGroups(rows: Record<string, unknown>[]): FundingGroup[] {
  const groups = new Map<string, FundingGroup & { capturedMinor: number; authorizedMinor: number; savedMinor: number; releasedMinor: number }>();
  for (const row of rows) {
    const kind = kindFromRow(row);
    const status = String(field(row, "status") ?? "").toLowerCase();
    if (!["captured", "partially_refunded", "refunded", "authorized", "vaulted", "voided"].includes(status)) continue;
    const preferred = kind === "project" ? field(row, "target_id") : field(row, "milestone_id");
    const target = String(preferred || field(row, "milestone_id") || field(row, "target_id") || "unassigned").trim();
    const key = `${kind}:${target}`;
    let group = groups.get(key);
    if (!group) {
      group = {
        id: target, kind, capturedEur: 0, authorizedEur: 0, savedEur: 0,
        releasedEur: 0, pledgeCount: 0,
        capturedMinor: 0, authorizedMinor: 0, savedMinor: 0, releasedMinor: 0,
      };
      groups.set(key, group);
    }
    const gross = amount(field(row, "amount_eur"));
    const netValue = field(row, "net_eur");
    const net = netValue === undefined ? gross : amount(netValue);
    if (status === "captured" || status === "partially_refunded" || status === "refunded") {
      group.capturedMinor += Math.min(gross, net);
    } else if (status === "authorized") {
      group.authorizedMinor += gross;
    } else if (status === "vaulted") {
      group.savedMinor += gross;
    } else if (status === "voided") {
      group.releasedMinor += gross;
    } else {
      continue;
    }
    group.pledgeCount += 1;
  }
  return Array.from(groups.values()).map(({ capturedMinor, authorizedMinor, savedMinor, releasedMinor, ...group }) => ({
    ...group,
    capturedEur: capturedMinor / 100,
    authorizedEur: authorizedMinor / 100,
    savedEur: savedMinor / 100,
    releasedEur: releasedMinor / 100,
  })).sort((a, b) =>
    (b.capturedEur + b.authorizedEur) - (a.capturedEur + a.authorizedEur)
    || a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id),
  );
}

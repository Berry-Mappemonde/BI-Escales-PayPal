import type { AgDataSourcesDefinition } from "ag-studio";
import { formatPledgeAmount, studioT } from "./locale";
import { dashboardCopy, ledgerStatus } from "./dashboardLocale";
import { dashboardMoney, ledgerTotals, totalFields, type LedgerPledge } from "./dashboardLedger";

export function pledgeStudioData(
  rows: LedgerPledge[], language = "en", currency = "EUR",
  labelFor: (row: LedgerPledge) => string = (row) => row.target,
): AgDataSourcesDefinition {
  const t = studioT(language);
  const copy = dashboardCopy(language);
  const amountFormatter = () => (value: unknown) => {
    if (value == null) return "—";
    return currency === "EUR"
      ? formatPledgeAmount(Number(value), language)
      : dashboardMoney(Number(value) * 100, currency, language);
  };
  const scoped = rows.filter((row) => row.currency === currency);
  const totals = ledgerTotals(scoped);
  return {
    description: t("studio.datasetDescription"),
    sources: [{
      id: "pledges",
      name: t("studio.sourceName"),
      data: scoped.map((row) => ({
        id: row.id,
        status: row.status,
        milestone_id: labelFor(row),
        kind: copy[row.type],
        amount_eur: row.pledged === null ? null : row.pledged / 100,
        net_eur: row.captured === null ? null : row.captured / 100,
      })),
      fields: [
        { id: "id", name: t("studio.colPledge"), format: "textFormat" },
        { id: "status", name: copy.status, format: "textFormat",
          createValueFormatter: () => (value) => ledgerStatus(String(value ?? ""), language) },
        { id: "milestone_id", name: copy.target, format: "textFormat" },
        { id: "kind", name: copy.type, format: "textFormat" },
        { id: "amount_eur", name: copy.pledged, format: "decimalFormat", createValueFormatter: amountFormatter },
        { id: "net_eur", name: t("studio.colNet"), format: "decimalFormat", createValueFormatter: amountFormatter },
      ],
    }, {
      id: "status_totals",
      name: copy.chartTitle,
      data: totalFields.flatMap((field) => {
        const total = totals[field];
        return total === null ? [] : [{ status: field, label: copy[field], amount: total / 100 }];
      }),
      fields: [
        { id: "status", name: copy.status, format: "textFormat",
          createValueFormatter: () => (value) => ledgerStatus(String(value ?? ""), language) },
        { id: "label", name: copy.chartTitle, format: "textFormat" },
        { id: "amount", name: t("studio.colAmount"), format: "decimalFormat", createValueFormatter: amountFormatter },
      ],
    }],
  };
}

import type { AgDataSourcesDefinition } from "ag-studio";
import type { PublicPledge } from "../api/types";
import { formatPledgeAmount, formatPledgeStatus, studioT } from "./locale";
import { toPledgeStudioRows } from "./pledgeRows";

export function pledgeStudioData(pledges: PublicPledge[], language?: string): AgDataSourcesDefinition {
  const t = studioT(language);
  const amountFormatter = () => (value: unknown) =>
    formatPledgeAmount(typeof value === "number" ? value : Number(value ?? 0), language);
  return {
    description: t("studio.datasetDescription"),
    sources: [
      {
        id: "pledges",
        name: t("studio.sourceName"),
        description: t("studio.sourceDescription"),
        data: toPledgeStudioRows(pledges),
        fields: [
          { id: "id", name: t("studio.colPledge"), format: "textFormat" },
          {
            id: "status",
            name: t("studio.colStatus"),
            format: "textFormat",
            createValueFormatter: () => (value) => formatPledgeStatus(String(value ?? ""), language),
          },
          { id: "milestone_id", name: t("studio.colMilestone"), format: "textFormat" },
          {
            id: "amount_eur",
            name: t("studio.colAmount"),
            format: "decimalFormat",
            createValueFormatter: amountFormatter,
          },
          {
            id: "net_eur",
            name: t("studio.colNet"),
            format: "decimalFormat",
            createValueFormatter: amountFormatter,
          },
          { id: "contributor", name: t("studio.colContributor"), format: "textFormat" },
          { id: "description", name: t("studio.colDescription"), format: "textFormat" },
          { id: "kind", name: language?.startsWith("en") ? "Funding type" : "Type de financement", format: "textFormat" },
          { id: "target_id", name: language?.startsWith("en") ? "Funding target" : "Projet ciblé", format: "textFormat" },
        ],
      },
    ],
  };
}

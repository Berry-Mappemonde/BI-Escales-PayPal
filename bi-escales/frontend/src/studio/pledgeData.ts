import type { AgDataSourcesDefinition } from "ag-studio";
import type { PublicPledge } from "../api/types";
import { toPledgeStudioRows } from "./pledgeRows";

export function pledgeStudioData(pledges: PublicPledge[]): AgDataSourcesDefinition {
  return {
    description:
      "Promesses PayPal sandbox BI Escales. Une autorisation n'est encaissée qu'après validation humaine du trésorier. Départ prévu le 15 mai 2027.",
    sources: [
      {
        id: "pledges",
        name: "Promesses",
        description:
          "Une ligne par promesse. amount_eur est en euros. status vaut created, authorized, captured ou voided.",
        data: toPledgeStudioRows(pledges),
        fields: [
          { id: "id", name: "Promesse", format: "textFormat" },
          { id: "status", name: "Statut", format: "textFormat" },
          { id: "milestone_id", name: "Jalon", format: "textFormat" },
          { id: "amount_eur", name: "Montant EUR", format: "decimalFormat" },
          { id: "contributor", name: "Contributeur", format: "textFormat" },
          { id: "description", name: "Description", format: "textFormat" },
        ],
      },
    ],
  };
}

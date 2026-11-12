import type { AgLlmRequest, AgLlmResponse } from "ag-studio";
import { totalFields, type LedgerTotals, type TotalField } from "./dashboardLedger";
import { studioLanguage } from "./locale";

export interface LedgerSummary {
  currency: string;
  totals: LedgerTotals;
}

const topicPatterns: Record<TotalField, RegExp> = {
  captured: /captur|encaiss|collect|\bnet\b/i,
  authorized: /authori[sz]|autoris|\bheld\b/i,
  vaulted: /vault|\bsaved\b|enregistr/i,
  voided: /void|cancel|releas|annul|libér/i,
  refunded: /refund|rembours/i,
};

/** Construct the proxy request from ledger totals and local topic matches only. */
export async function askLedgerModel(
  endpoint: string,
  { currency, totals }: LedgerSummary,
  question: string,
  language: string,
  signal?: AbortSignal,
): Promise<string | undefined> {
  const focus = totalFields.filter((field) => topicPatterns[field].test(question));
  const amounts = Object.fromEntries(totalFields.map((field) => {
    const amount = totals[field];
    return [field, amount !== null && Number.isFinite(amount) ? amount / 100 : null];
  }));
  const request: AgLlmRequest = {
    instructions: [
      `Reply in ${studioLanguage(language) === "fr" ? "French" : "English"} as a read-only treasurer assistant.`,
      "Summarize the ledger totals provided. If focus contains statuses, emphasize those totals.",
      "Captured means net after refunds. Authorized, vaulted, and voided amounts are outside captured funds.",
      "All amounts are in the stated currency, and null means unavailable. Do not infer individual transactions.",
    ].join(" "),
    input: [{
      id: "ledger-summary",
      kind: "input",
      type: "message",
      role: "user",
      status: "completed",
      content: [{
        type: "text",
        text: JSON.stringify({ currency: /^[A-Z]{3}$/.test(currency) ? currency : null, focus, amounts }),
      }],
    }],
    toolChoice: "none",
    responseFormat: { type: "text" },
  };

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ request }),
      signal,
    });
    if (!response.ok) return undefined;
    const result = (await response.json()) as AgLlmResponse;
    if (result.status !== "completed" || result.error) return undefined;
    return result.output.flatMap((item) => item.type === "message"
      ? item.content.flatMap((part) => part.type === "text" ? [part.text] : [])
      : []).join("\n").trim() || undefined;
  } catch {
    return undefined;
  }
}

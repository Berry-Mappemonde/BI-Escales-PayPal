import { studioT } from "./locale";

export const VALIDATION_WIDGET_TYPE = "validation-humaine";
export const VALIDATION_NOTE_ID = "validation-note";
export const FUNDING_WIDGET_TYPE = "funding-milestones";
export const FUNDING_WIDGET_ID = "funding-milestone-agent";

export type TreasurerAction =
  | { kind: "delegate-data"; instructions: string }
  | { kind: "add-validation-widget" }
  | { kind: "add-funding-widget" }
  | { kind: "reply" };

export type DataAgentAction = { kind: "view-schema" } | { kind: "complete"; summary: string };

const FUNDING_REQUEST = /\b(crowdfunding|funding|financement|campagne de financement)\b/i;
const ADD_WIDGET = /\b(widget|jauge|scoreboard|ajouter|ajoute|add)\b/i;

export function wantsValidationWidget(userText: string): boolean {
  return ADD_WIDGET.test(userText);
}

/**
 * The treasurer agent delegates the first turn to Studio's built-in data agent,
 * then optionally places a read-only widget, then stops.
 */
export function nextTreasurerAction(
  userText: string,
  toolMessageCount: number,
  language?: string,
): TreasurerAction {
  if (toolMessageCount <= 0) {
    const instructions = userText.trim() || studioT(language)("studio.delegateFallback");
    return { kind: "delegate-data", instructions };
  }
  if (toolMessageCount === 1 && FUNDING_REQUEST.test(userText)) {
    return { kind: "add-funding-widget" };
  }
  if (wantsValidationWidget(userText) && toolMessageCount === 1) {
    return { kind: "add-validation-widget" };
  }
  return { kind: "reply" };
}

/** Built-in data agent, driven without an LLM: read the schema, then hand the summary back. */
export function nextDataAgentAction(
  toolMessageCount: number,
  schemaText: string,
  language?: string,
): DataAgentAction {
  if (toolMessageCount <= 0) return { kind: "view-schema" };
  const t = studioT(language);
  const excerpt = schemaText.replace(/\s+/g, " ").trim().slice(0, 240);
  const summary = excerpt
    ? t("studio.dataAgentSummary", { excerpt })
    : t("studio.dataAgentSummaryEmpty");
  return { kind: "complete", summary };
}

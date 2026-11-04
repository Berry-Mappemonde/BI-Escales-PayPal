import type { AgDefaultRegistry, AgWidgetFormParams, AgWidgetsConfig } from "ag-studio";
import { createWidgets } from "ag-studio-react";
import { VALIDATION_WIDGET_TYPE } from "./agentPlan";
import { ValidationScoreboard } from "./validationWidget";

const ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 6v20M6 16h20" stroke="currentColor" stroke-width="2"/></svg>';

/**
 * Registers the human-validation scoreboard next to Studio's built-in widgets.
 * The helper's registry generic only lists stock widget ids, so the extra id is
 * passed through at the call boundary.
 */
export function escalesWidgets(
  widgetConfig: AgWidgetsConfig<AgDefaultRegistry>,
): AgWidgetsConfig<AgDefaultRegistry> {
  const params = {
    additionalTypes: [
      {
        id: VALIDATION_WIDGET_TYPE,
        label: "Validation humaine",
        icon: ICON,
        dataMapping: {
          status: {
            type: "field" as const,
            supportedRoles: ["category" as const],
            requires: { cardinality: "many" as const },
            required: false,
          },
          amount: {
            type: "field" as const,
            supportedRoles: ["numeric" as const],
            requires: { per: "dataMapping.status", cardinality: "one" as const },
            required: false,
          },
        },
        form: (params: AgWidgetFormParams) =>
          params.createDefaults({
            dataMappingItems: [
              { key: "status", label: "Statut" },
              { key: "amount", label: "Montant" },
            ],
          }),
        comp: ValidationScoreboard,
        defaultSize: { width: 480, height: 220 },
        minSize: { width: 220, height: 140 },
        ai: {
          description:
            "Scoreboard of authorized, captured and voided pledge totals. States that a human treasurer must validate before any capture.",
          usage: "Use for the BI Escales human-validation rule. Map status and amount (sum).",
        },
      },
    ],
    menu: [
      { label: "BI Escales", widgetIds: [VALIDATION_WIDGET_TYPE] },
      ...widgetConfig.menu,
    ],
  };
  return createWidgets(params as never) as AgWidgetsConfig<AgDefaultRegistry>;
}

import type { AgDefaultRegistry, AgWidgetFormParams, AgWidgetsConfig } from "ag-studio";
import { createWidgets } from "ag-studio-react";
import { FUNDING_WIDGET_TYPE, VALIDATION_WIDGET_TYPE } from "./agentPlan";
import { FundingMilestoneWidget } from "./fundingMilestoneWidget";
import { studioT } from "./locale";
import { ValidationScoreboard } from "./validationWidget";

const ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 6v20M6 16h20" stroke="currentColor" stroke-width="2"/></svg>';

/**
 * Registers the human-validation scoreboard next to Studio's built-in widgets.
 * The helper's registry generic only lists stock widget ids, so the extra id is
 * passed through at the call boundary.
 */
export function humanValidationWidget(language?: string) {
  const t = studioT(language);
  return {
    id: VALIDATION_WIDGET_TYPE,
    label: t("studio.widgetLabel"),
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
          { key: "status", label: t("studio.colStatus") },
          { key: "amount", label: t("studio.colAmount") },
        ],
      }),
    comp: ValidationScoreboard,
    defaultSize: { width: 480, height: 220 },
    minSize: { width: 220, height: 140 },
    ai: {
      description: t("studio.widgetAiDescription"),
      usage: t("studio.widgetAiUsage"),
    },
  };
}

export function fundingMilestoneWidget(language?: string) {
  return {
    id: FUNDING_WIDGET_TYPE,
    label: language?.startsWith("en") ? "Project funding by milestone" : "Financement par projet",
    icon: ICON,
    dataMapping: {},
    comp: FundingMilestoneWidget,
    defaultSize: { width: 900, height: 320 },
    minSize: { width: 430, height: 200 },
    ai: {
      description: "Show real captured, authorized, vaulted and released amounts by marine project, stopover or common fund.",
      usage: "Use for crowdfunding, project funding, milestone finance or campaign questions. Never initiate a payment.",
    },
  };
}

export function escalesWidgets(
  widgetConfig: AgWidgetsConfig<AgDefaultRegistry>,
  language?: string,
): AgWidgetsConfig<AgDefaultRegistry> {
  const params = {
    additionalTypes: [humanValidationWidget(language), fundingMilestoneWidget(language)],
    menu: [
      { label: "BI Escales", widgetIds: [VALIDATION_WIDGET_TYPE, FUNDING_WIDGET_TYPE] },
      ...widgetConfig.menu,
    ],
  };
  return createWidgets(params as never) as AgWidgetsConfig<AgDefaultRegistry>;
}

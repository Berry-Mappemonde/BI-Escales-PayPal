import type { AgReportState } from "ag-studio";
import { VALIDATION_WIDGET_TYPE } from "./agentPlan";
import { studioT } from "./locale";

const PLEDGES = "pledges";

/** Opening treasurer report: custom scoreboard, status chart, pledge grid. */
export function treasurerInitialState(language?: string): AgReportState {
  const t = studioT(language);
  return {
    selectedPageId: "tresorerie",
    panels: {
      filters: { collapsed: true },
      data: { collapsed: true },
      ai: { collapsed: true },
      edit: { collapsed: true },
    },
    pages: [
      {
        id: "tresorerie",
        layout: { columns: 24, rowHeight: 22 },
        widgets: {
          validation: {
            type: VALIDATION_WIDGET_TYPE,
            dataMapping: {
              status: [{ id: `${PLEDGES}.status` }],
              amount: [{ id: `${PLEDGES}.net_eur`, aggregation: "sum" }],
            },
            format: { title: { enabled: true, text: t("studio.scoreTitle") } },
          },
          "status-chart": {
            type: "column-chart-grouped",
            dataMapping: {
              categoryKey: [{ id: `${PLEDGES}.status` }],
              valueKey: [{ id: `${PLEDGES}.net_eur`, aggregation: "sum" }],
            },
            format: { title: { enabled: true, text: t("studio.chartTitle") } },
          },
          "pledge-grid": {
            type: "grid",
            dataMapping: {
              cols: [
                { id: `${PLEDGES}.id` },
                { id: `${PLEDGES}.milestone_id` },
                { id: `${PLEDGES}.status` },
                { id: `${PLEDGES}.amount_eur` },
                { id: `${PLEDGES}.net_eur` },
                { id: `${PLEDGES}.contributor` },
                { id: `${PLEDGES}.description` },
              ],
            },
            format: { title: { enabled: true, text: t("studio.gridTitle") } },
          },
        },
        widgetLayout: {
          validation: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 8 },
          "status-chart": { xTrack: 0, yTrack: 8, xSpan: 10, ySpan: 16 },
          "pledge-grid": { xTrack: 10, yTrack: 8, xSpan: 14, ySpan: 16 },
        },
      },
    ],
  } as unknown as AgReportState;
}

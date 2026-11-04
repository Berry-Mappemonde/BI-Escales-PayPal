import type { AgReportState } from "ag-studio";
import { VALIDATION_WIDGET_TYPE } from "./agentPlan";

const PLEDGES = "pledges";

/** Opening treasurer report: custom scoreboard, status chart, pledge grid. */
export function treasurerInitialState(): AgReportState {
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
              amount: [{ id: `${PLEDGES}.amount_eur`, aggregation: "sum" }],
            },
            format: { title: { enabled: true, text: "Validation humaine" } },
          },
          "status-chart": {
            type: "column-chart-grouped",
            dataMapping: {
              categoryKey: [{ id: `${PLEDGES}.status` }],
              valueKey: [{ id: `${PLEDGES}.amount_eur`, aggregation: "sum" }],
            },
            format: { title: { enabled: true, text: "Montants par statut" } },
          },
          "pledge-grid": {
            type: "grid",
            dataMapping: {
              cols: [
                { id: `${PLEDGES}.id` },
                { id: `${PLEDGES}.milestone_id` },
                { id: `${PLEDGES}.status` },
                { id: `${PLEDGES}.amount_eur` },
                { id: `${PLEDGES}.contributor` },
                { id: `${PLEDGES}.description` },
              ],
            },
            format: { title: { enabled: true, text: "Promesses" } },
          },
        },
        widgetLayout: {
          validation: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 8 },
          "status-chart": { xTrack: 0, yTrack: 8, xSpan: 12, ySpan: 14 },
          "pledge-grid": { xTrack: 12, yTrack: 8, xSpan: 12, ySpan: 14 },
        },
      },
    ],
  } as unknown as AgReportState;
}

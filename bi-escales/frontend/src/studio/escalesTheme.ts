import { studioTheme } from "ag-studio";

/** Night theme aligned with the BI Escales shell (see styles/app.css). */
export const escalesStudioTheme = studioTheme.withParams(
  {
    fontFamily: '"Segoe UI", system-ui, sans-serif',
    fontSize: 14,
    backgroundColor: "#122a42",
    foregroundColor: "#e8f1facc",
    textColor: "#e8f1fa",
    subtleTextColor: "#9fb6cc",
    accentColor: "#3d9be9",
    borderColor: "#3d9be955",
    iconColor: "#9fb6cc",
    rowHoverColor: "#3d9be922",
    browserColorScheme: "dark",
    studioWrapperBackgroundColor: "#0b1f33",
    studioCanvasBackgroundColor: "#0b1f33",
    studioCanvasPadding: 12,
    studioWidgetBackgroundColor: "#122a42",
    studioWidgetBorderRadius: 8,
    gridHeaderBackgroundColor: "#0e2438",
    gridHeaderTextColor: "#9fb6cc",
    gridCellTextColor: "#e8f1fa",
    chartAxisLineColor: "#3d9be955",
    chartPaletteFills1Color: "#3d9be9",
    chartPaletteFills2Color: "#7fd992",
    chartPaletteFills3Color: "#e8b84a",
    chartPaletteFills4Color: "#f07178",
  },
  "escales-night",
);

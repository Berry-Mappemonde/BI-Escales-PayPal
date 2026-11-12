import { studioTheme } from "ag-studio";

const theme = studioTheme.withParams({
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  backgroundColor: "var(--color-panel)",
  foregroundColor: "var(--color-fg)",
  textColor: "var(--color-fg)",
  subtleTextColor: "var(--color-fg-2)",
  accentColor: "var(--color-accent)",
  borderColor: "var(--color-line)",
  iconColor: "var(--color-fg-2)",
  rowHoverColor: "var(--color-raised)",
  studioWrapperBackgroundColor: "var(--color-canvas)",
  studioCanvasBackgroundColor: "var(--color-canvas)",
  studioCanvasPadding: 12,
  studioWidgetBackgroundColor: "var(--color-panel)",
  studioWidgetBorderRadius: "var(--radius-panel)",
  gridHeaderBackgroundColor: "var(--color-raised)",
  gridHeaderTextColor: "var(--color-fg-2)",
  gridCellTextColor: "var(--color-fg)",
  chartAxisLineColor: "var(--color-line)",
  chartPaletteFills1Color: "var(--color-accent)",
  chartPaletteFills2Color: "var(--color-status-captured)",
  chartPaletteFills3Color: "var(--color-status-held)",
  chartPaletteFills4Color: "var(--color-status-refunded)",
});

export const escalesStudioTheme = theme
  .withParams({ browserColorScheme: "dark" }, "dark")
  .withParams({ browserColorScheme: "light" }, "light");

export const LEAFLET_BUILTIN_PANES = {
  tilePane: 200,
  overlayPane: 400,
  shadowPane: 500,
  markerPane: 600,
  tooltipPane: 650,
  popupPane: 700,
};

export const PANES = [
  { name: "science-wms-bathy", zIndex: 240, pointerEvents: "none" },
  { name: "zee-wms", zIndex: 250 },
  { name: "science-wms-substrate", zIndex: 255, pointerEvents: "none" },
  { name: "balisage", zIndex: 260 },
  { name: "science-wms-cables", zIndex: 270, pointerEvents: "none" },
  { name: "climatology-raster", zIndex: 350, pointerEvents: "none" },
  { name: "climatology-vector", zIndex: 370, pointerEvents: "none" },
  { name: "route", zIndex: 380 },
  { name: "science-tracks", zIndex: 410 },
  { name: "amp", zIndex: 420 },
  { name: "grib", zIndex: 560, pointerEvents: "none" },
  { name: "boat", zIndex: 620 },
  // The dashed briefing line is not clickable. Its canvas must not cover the flags.
  { name: "briefing-focus", zIndex: 630, pointerEvents: "none" },
];

export function createPanes(map) {
  PANES.forEach(({ name, zIndex, pointerEvents }) => {
    map.createPane(name);
    const pane = map.getPane(name);
    pane.style.zIndex = String(zIndex);
    if (pointerEvents) pane.style.pointerEvents = pointerEvents;
  });
}

export function paneOrder() {
  return PANES.map((p) => p.name);
}

/** Z-index d'un pan Leaflet, overlay par défaut. */
export function paneZIndex(name) {
  if (!name || name === "overlayPane") return LEAFLET_BUILTIN_PANES.overlayPane;
  const pane = PANES.find((item) => item.name === name);
  return pane ? pane.zIndex : LEAFLET_BUILTIN_PANES.overlayPane;
}

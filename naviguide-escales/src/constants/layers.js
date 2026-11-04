export const BI_COLORS = {
  biProjects: "#06b6d4",
  biMarinas: "#ef4444",
  biCapitaineries: "#7dd3fc",
  biPoe: "#d97706",
  biAmp: "#22c55e",
};

export const DEFAULT_SHOW_ZEE = false;
export const DEFAULT_SHOW_GRIB = false;

export const ALL_LAYER_CONFIG = [
  { key: "grib2", labelKey: "layerGrib2", titleKey: "layerGrib2Title", color: "#22d3ee", showKey: "showGrib", toggleKey: "setShowGrib", loadingKey: "loadingGrib", errorKey: "errorGrib" },
  { key: "zee", labelKey: "layerZee", titleKey: "layerZeeTitle", color: "#0e7490", showKey: "showZee", toggleKey: "setShowZee", loadingKey: "loadingZee", errorKey: "errorZee" },
  { key: "wpi", labelKey: "layerPorts", titleKey: "layerPortsTitle", color: "#f59e0b", showKey: "showPorts", toggleKey: "setShowPorts", loadingKey: "loadingPorts", errorKey: "errorPorts" },
  { key: "balisage", labelKey: "layerBalisage", titleKey: "layerBalisageTitle", color: "#10b981", showKey: "showBalisage", toggleKey: "setShowBalisage", loadingKey: "loadingBalisage", errorKey: "errorBalisage" },
  { key: "projects", labelKey: "layerBiProjects", titleKey: "layerBiProjectsTitle", color: BI_COLORS.biProjects, showKey: "showBiProjects", toggleKey: "setShowBiProjects", loadingKey: "loadingBiProjects", errorKey: "errorBiProjects" },
  { key: "marinas", labelKey: "layerBiMarinas", titleKey: "layerBiMarinasTitle", color: BI_COLORS.biMarinas, showKey: "showBiMarinas", toggleKey: "setShowBiMarinas", loadingKey: "loadingBiMarinas", errorKey: "errorBiMarinas" },
  { key: "capitaineries", labelKey: "layerBiCapitaineries", titleKey: "layerBiCapitaineriesTitle", color: BI_COLORS.biCapitaineries, showKey: "showBiCapitaineries", toggleKey: "setShowBiCapitaineries", loadingKey: "loadingBiCapitaineries", errorKey: "errorBiCapitaineries" },
  { key: "poe", labelKey: "layerBiPoe", titleKey: "layerBiPoeTitle", color: BI_COLORS.biPoe, showKey: "showBiPoe", toggleKey: "setShowBiPoe", loadingKey: "loadingBiPoe", errorKey: "errorBiPoe" },
  { key: "amp", labelKey: "layerBiAmp", titleKey: "layerBiAmpTitle", color: BI_COLORS.biAmp, showKey: "showBiAmp", toggleKey: "setShowBiAmp", loadingKey: "loadingBiAmp", errorKey: "errorBiAmp" },
  { key: "sextant", labelKey: "layerSextant", titleKey: "layerSextantTitle", color: "#a78bfa", showKey: "showSextant", toggleKey: "setShowSextant", loadingKey: "loadingScienceCatalog", errorKey: "errorScienceCatalog" },
  { key: "argo", labelKey: "layerArgo", titleKey: "layerArgoTitle", color: "#c4b5fd", showKey: "showArgo", toggleKey: "setShowArgo", loadingKey: "loadingScienceCatalog", errorKey: "errorScienceCatalog" },
  { key: "odatis", labelKey: "layerOdatis", titleKey: "layerOdatisTitle", color: "#8b5cf6", showKey: "showOdatis", toggleKey: "setShowOdatis", loadingKey: "loadingScienceCatalog", errorKey: "errorScienceCatalog" },
  { key: "edmed", labelKey: "layerEdmed", titleKey: "layerEdmedTitle", color: "#7c3aed", showKey: "showEdmed", toggleKey: "setShowEdmed", loadingKey: "loadingScienceCatalog", errorKey: "errorScienceCatalog" },
  { key: "csr", labelKey: "layerCsr", titleKey: "layerCsrTitle", color: "#6d28d9", showKey: "showCsr", toggleKey: "setShowCsr", loadingKey: "loadingScienceCatalog", errorKey: "errorScienceCatalog" },
  { key: "bathymetry", labelKey: "layerBathymetry", titleKey: "layerBathymetryTitle", color: "#0ea5e9", showKey: "showBathymetry", toggleKey: "setShowBathymetry", loadingKey: "loadingBathymetry", errorKey: "errorBathymetry" },
  { key: "fonds", labelKey: "layerFonds", titleKey: "layerFondsTitle", color: "#ca8a04", showKey: "showFonds", toggleKey: "setShowFonds", loadingKey: "loadingFonds", errorKey: "errorFonds" },
  { key: "cables", labelKey: "layerCables", titleKey: "layerCablesTitle", color: "#fb7185", showKey: "showCables", toggleKey: "setShowCables", loadingKey: "loadingCables", errorKey: "errorCables" },
  { key: "climo-wind", labelKey: "layerClimoWind", titleKey: "layerClimoWindTitle", color: "#38bdf8", showKey: "showClimoWind", toggleKey: "setShowClimoWind", loadingKey: "loadingClimoWind", errorKey: "errorClimatology" },
  { key: "climo-wave", labelKey: "layerClimoWave", titleKey: "layerClimoWaveTitle", color: "#2dd4bf", showKey: "showClimoWave", toggleKey: "setShowClimoWave", loadingKey: "loadingClimoWave", errorKey: "errorClimatology" },
  { key: "climo-current", labelKey: "layerClimoCurrent", titleKey: "layerClimoCurrentTitle", color: "#f59e0b", showKey: "showClimoCurrent", toggleKey: "setShowClimoCurrent", loadingKey: "loadingClimoCurrent", errorKey: "errorClimatology" },
  { key: "climo-cyclones", labelKey: "layerClimoCyclones", titleKey: "layerClimoCyclonesTitle", color: "#f87171", showKey: "showClimoCyclones", toggleKey: "setShowClimoCyclones", loadingKey: "loadingClimoCyclones", errorKey: "errorClimatology" },
];

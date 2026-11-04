import {
  EMODNET_ACTIVITIES_ATTRIBUTION,
  EMODNET_BATHYMETRY_ATTRIBUTION,
  EMODNET_GEOLOGY_ATTRIBUTION,
} from "./tileAttributions.js";

/** EMODnet WMS — same layers as Blue Intelligence Science mode. */
export const SCIENCE_WMS_LAYERS = [
  {
    id: "bathymetry",
    url: "https://ows.emodnet-bathymetry.eu/wms",
    layers: "mean_multicolour",
    opacity: 0.5,
    pane: "science-wms-bathy",
    attribution: EMODNET_BATHYMETRY_ATTRIBUTION,
  },
  {
    id: "substrate",
    url: "https://drive.emodnet-geology.eu/geoserver/gtk/wms",
    layers: "seabed_substrate_1m",
    opacity: 0.75,
    pane: "science-wms-substrate",
    attribution: EMODNET_GEOLOGY_ATTRIBUTION,
  },
  {
    id: "cables",
    url: "https://ows.emodnet-humanactivities.eu/wms",
    layers: "telecablesactual,powercables",
    opacity: 1,
    pane: "science-wms-cables",
    attribution: EMODNET_ACTIVITIES_ATTRIBUTION,
  },
];

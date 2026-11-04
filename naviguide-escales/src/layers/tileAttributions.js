/**
 * Credits for raster tile / WMS layers. Leaflet only keeps a layer option
 * credit while that layer instance is on the map; the seamark fallback removes
 * the first instance, so the control is updated here for the whole toggle.
 */

export const OPENSEAMAP_ATTRIBUTION = "© OpenSeaMap contributors";

export const OSM_COPYRIGHT_HREF = "https://www.openstreetmap.org/copyright";

export const CC_BY_4_HREF = "https://creativecommons.org/licenses/by/4.0/";

const CC_BY_4 = `<a href="${CC_BY_4_HREF}" target="_blank" rel="noopener noreferrer">CC-BY 4.0</a>`;

/** EMODnet Bathymetry WMS (`mean_multicolour`), CC-BY 4.0. Not the GEBCO point lookup. */
export const EMODNET_BATHYMETRY_ATTRIBUTION =
  `© <a href="https://emodnet.ec.europa.eu/en/bathymetry" target="_blank" rel="noopener noreferrer">EMODnet Bathymetry Consortium</a> (${CC_BY_4})`;

export const EMODNET_GEOLOGY_ATTRIBUTION =
  `© <a href="https://emodnet.ec.europa.eu/en/geology" target="_blank" rel="noopener noreferrer">EMODnet Geology</a> (${CC_BY_4})`;

export const EMODNET_ACTIVITIES_ATTRIBUTION =
  `© <a href="https://emodnet.ec.europa.eu/en/human-activities" target="_blank" rel="noopener noreferrer">EMODnet Human Activities</a> (${CC_BY_4})`;

/** Marine Regions EEZ WMS proxied at `/proxy/zee/wms`. */
export const VLIZ_EEZ_ATTRIBUTION =
  `© <a href="https://www.marineregions.org/" target="_blank" rel="noopener noreferrer">Flanders Marine Institute (VLIZ)</a>, Marine Regions, ${CC_BY_4}`;

/** Register one credit on Leaflet's attribution control until the returned function runs. */
export function bindTileCredit(map, html) {
  const control = map?.attributionControl;
  if (!control || !html) return () => {};
  control.addAttribution(html);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    control.removeAttribution(html);
  };
}

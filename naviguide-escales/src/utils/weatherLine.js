/** Une seule mention Open-Meteo, sous la barre. */
export const WEATHER_LINE = "GFS + GFS-Wave (Open-Meteo)";

export function weatherLine({ isSuivre, gribReady } = {}) {
  if (isSuivre && gribReady) return WEATHER_LINE;
  return "";
}

export function countOpenMeteo(text) {
  return (String(text || "").match(/Open-Meteo/gi) || []).length;
}

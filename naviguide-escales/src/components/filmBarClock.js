export const PROFILES = [
  { id: "real", labelKey: "speedReal" },
  { id: "read", labelKey: "speedRead" },
  { id: "normal", labelKey: "speedNormal" },
  { id: "fast", labelKey: "speedFast" },
];

const GFS_SOURCE_RE = /gfs|om-forecast|open-?meteo/i;

export function nextFilmSpeed(current) {
  const i = PROFILES.findIndex((p) => p.id === current);
  if (i < 0) return PROFILES[0].id;
  return PROFILES[(i + 1) % PROFILES.length].id;
}

/** GFS du *point* : régime prévision, ou une source GFS / om-forecast / Open-Meteo.
 *  `weatherLine` (mention globale « GFS + GFS-Wave (Open-Meteo) ») n'est pas une preuve. */
export function weatherUsesGfs({ regime, sources }) {
  if (regime === "forecast") return true;
  return (Array.isArray(sources) ? sources : []).some((s) => GFS_SOURCE_RE.test(String(s || "")));
}

/** « réel jusqu'au 9 oct. » — date courte localisée, ou null sans realUntil. */
export function realUntilLabel(realUntil, t, lang = "fr") {
  if (!realUntil) return null;
  const d = new Date(`${realUntil}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  const loc = lang === "en" ? "en-US" : "fr-FR";
  const date = d.toLocaleDateString(loc, { day: "numeric", month: "short", timeZone: "UTC" });
  return t("clockRegimeRealUntil", { date });
}

export function clockRegimeText({ regime, sources, spread, realUntil, t, lang = "fr" }) {
  const climo = regime === "climatology";
  const gfs = weatherUsesGfs({ regime, sources });
  const real = realUntilLabel(realUntil, t, lang);
  if (climo && gfs) return real ? `${t("clockWeatherClimoGfs")} · ${real}` : t("clockWeatherClimoGfs");
  if (climo) return real ? `${t("clockRegimeClimatology")} · ${real}` : t("clockRegimeClimatology");
  if (regime === "hindcast") {
    const name = real || t("clockRegimeHindcast");
    const n = Array.isArray(sources) ? sources.length : 0;
    const loc = lang === "en" ? "en-US" : "fr-FR";
    if (n > 0 && Number.isFinite(Number(spread))) {
      const sp = Number(spread).toLocaleString(loc, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      return `${name} · ${t("clockRegimeSources", { n, spread: sp })}`;
    }
    if (n > 0) return `${name} · ${t("clockRegimeSourcesPlain", { n })}`;
    return name;
  }
  if (gfs) return t("clockWeatherGfs");
  if (regime === "forecast") return t("clockRegimeForecast");
  return "";
}

export function clockWeatherTooltip({ sources, spread, weatherLine, regimeTitle, t, lang = "fr" }) {
  const bits = [];
  if (weatherLine) bits.push(weatherLine);
  const list = Array.isArray(sources) ? sources.filter(Boolean) : [];
  if (list.length) bits.push(list.join(" · "));
  if (list.length && Number.isFinite(Number(spread))) {
    const loc = lang === "en" ? "en-US" : "fr-FR";
    const sp = Number(spread).toLocaleString(loc, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    bits.push(t("clockRegimeSources", { n: list.length, spread: sp }));
  }
  if (regimeTitle) bits.push(regimeTitle);
  return bits.filter(Boolean).join(" · ");
}

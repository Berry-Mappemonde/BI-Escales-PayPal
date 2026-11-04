/**
 * Revue de plan par règles — mise en mots côté client, pur, testé.
 * Le serveur fournit les jambes (calendrier, ZEE, ports d'entrée, AMP,
 * perles inconnues) ; l'atlas déjà en cache fournit la saison du mois de la
 * jambe (rose des vents, cyclones IBTrACS). Aucun chiffre inventé : une
 * donnée absente donne une ligne « non chargé », pas une estimation.
 */

const GALE_PCT_DEFAULT = 15;

function isEn(lang) { return String(lang || "").toLowerCase().startsWith("en"); }

function dayMonth(iso, lang) {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  return new Date(t).toLocaleDateString(isEn(lang) ? "en-GB" : "fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });
}

/**
 * Season of a leg from the atlas cache: `lookup(lat, lon, month)` → { point }
 * for sample points of the leg. Returns { galePct, cyclones, cells, missing }.
 */
export function seasonFromAtlas(leg, samplePoints, lookup) {
  let galePct = null;
  let cyclones = null;
  let cells = 0;
  let missing = 0;
  for (const p of samplePoints || []) {
    const hit = typeof lookup === "function" ? lookup(p.lat, p.lon, leg.month) : null;
    const point = hit?.point;
    if (!point) { missing += 1; continue; }
    cells += 1;
    const g = point.rose?.gale_pct ?? point.wind_atlas?.gale_pct ?? point.gale_pct;
    if (Number.isFinite(Number(g))) galePct = Math.max(galePct ?? 0, Number(g));
    const c = point.cyclone?.nearby;
    if (Number.isFinite(Number(c))) cyclones = Math.max(cyclones ?? 0, Number(c));
  }
  return { galePct, cyclones, cells, missing };
}

/** One leg → { title, dates, badges: [{ kind, text, level }], notes: [string] }. */
export function reviewLeg(leg, season, lang = "fr", { galeLimitPct = GALE_PCT_DEFAULT } = {}) {
  const en = isEn(lang);
  const badges = [];
  const notes = [];
  const days = Number.isFinite(Number(leg.daysAtSea)) ? Number(leg.daysAtSea) : 0;
  badges.push({ kind: "sea", level: "info", text: en ? `${leg.legNm} nm · ${days} d at sea` : `${leg.legNm} nm · ${days} j de mer` });
  if (leg.holdDays > 0) {
    badges.push({ kind: "rest", level: "info", text: en ? `${leg.holdDays} d alongside` : `${leg.holdDays} j à quai` });
  } else if (days >= 3) {
    badges.push({ kind: "rest", level: "watch", text: en ? "no rest planned" : "pas de repos prévu" });
  }
  const zees = leg.zees || [];
  if (zees.length) {
    const gold = zees.filter((z) => z.gold).length;
    badges.push({ kind: "zee", level: gold === zees.length ? "ok" : "watch", text: en ? `${zees.length} EEZ · ${gold} Gold` : `${zees.length} ZEE · ${gold} Gold` });
  }
  const form = (leg.flags || []).find((f) => f.kind === "formalities");
  if (form?.names?.length) {
    notes.push(en
      ? `Formalities to check: ${form.names.join(", ")} (no Gold pack, no known port of entry).`
      : `Formalités à vérifier : ${form.names.join(", ")} (sans dossier Gold ni port d’entrée connu).`);
  }
  if (leg.ampCount > 0) {
    badges.push({ kind: "amp", level: "info", text: en ? `${leg.ampCount} MPA` : `${leg.ampCount} AMP` });
  }
  if (season) {
    if (season.cells === 0) {
      badges.push({ kind: "season", level: "muted", text: en ? "season: atlas not loaded" : "saison : atlas non chargé" });
    } else {
      if (season.galePct != null) {
        const hot = season.galePct >= galeLimitPct;
        badges.push({ kind: "gale", level: hot ? "alert" : "ok", text: en ? `gale ${Math.round(season.galePct)} % of the time` : `coup de vent ${Math.round(season.galePct)} % du temps` });
        if (hot) notes.push(en ? `Windy season on this leg (gale ${Math.round(season.galePct)} % ≥ ${galeLimitPct} %).` : `Saison ventée sur cette jambe (coup de vent ${Math.round(season.galePct)} % ≥ ${galeLimitPct} %).`);
      }
      if (season.cyclones != null) {
        badges.push({ kind: "cyclone", level: season.cyclones > 0 ? "alert" : "ok", text: season.cyclones > 0
          ? (en ? `${season.cyclones} historical cyclone track${season.cyclones > 1 ? "s" : ""} nearby` : `${season.cyclones} trajectoire${season.cyclones > 1 ? "s" : ""} cyclonique${season.cyclones > 1 ? "s" : ""} à proximité`)
          : (en ? "no historical cyclone nearby" : "aucun cyclone historique à proximité") });
      }
    }
  }
  const unknown = leg.pearls?.unknown || 0;
  if (unknown && !(leg.pearls?.known)) {
    badges.push({ kind: "pearls", level: "muted", text: en ? "pearls not warmed yet" : "perles pas encore chauffées" });
  }
  const pack = leg.antiShipping && typeof leg.antiShipping === "object" ? leg.antiShipping : null;
  const lanes = Array.isArray(pack?.lanes)
    ? pack.lanes.filter((n) => typeof n === "string" && n.trim())
    : [];
  const score = Number(pack?.score);
  const badgeAlerts = badges.filter((b) => b.level === "alert").length;
  const given = Number(leg.alertCount);
  const alertCount = Number.isFinite(given) ? given : badgeAlerts;
  return {
    key: `${leg.from}→${leg.to}`,
    title: `${leg.from} → ${leg.to}`,
    dates: `${dayMonth(leg.departIso, lang)} → ${dayMonth(leg.arriveIso, lang)}`,
    departIso: leg.departIso || null,
    month: leg.month,
    from: leg.from,
    to: leg.to,
    legNm: Number.isFinite(Number(leg.legNm)) ? Number(leg.legNm) : null,
    daysAtSea: Number.isFinite(Number(leg.daysAtSea)) ? Number(leg.daysAtSea) : null,
    alertCount,
    badges,
    notes,
    antiShipping: lanes.length ? { score: Number.isFinite(score) ? score : null, lanes } : null,
    level: badges.some((b) => b.level === "alert") ? "alert" : (badges.some((b) => b.level === "watch") || notes.length ? "watch" : "ok"),
  };
}

/** Sample points of a leg from the clock vertices (sea miles bounds), at most `n`. */
export function legSamplePoints(clock, leg, n = 5) {
  const verts = (clock?.vertices || []).filter((v) => Number.isFinite(v.sailNm) && v.sailNm >= leg.fromNm - 0.5 && v.sailNm <= leg.toNm + 0.5 && Number.isFinite(v.lat));
  if (!verts.length) return [];
  const step = Math.max(1, Math.floor(verts.length / n));
  const out = [];
  for (let i = 0; i < verts.length && out.length < n; i += step) out.push({ lat: verts[i].lat, lon: verts[i].lon });
  return out;
}

/**
 * Season of a leg: the server's reading (BI atlas, cached) when it has one,
 * else the client's atlas cache. Two honest sources, never an estimate.
 */
export function seasonForLeg(leg, clock, lookup) {
  const s = leg?.season;
  if (s && Number.isFinite(s.cells) && s.cells > 0) return { galePct: s.galePct ?? null, cyclones: s.cyclones ?? null, cells: s.cells, missing: s.missing || 0 };
  const local = seasonFromAtlas(leg, legSamplePoints(clock, leg), lookup);
  if (local.cells > 0) return local;
  return { galePct: null, cyclones: null, cells: 0, missing: (s?.missing || 0) + local.missing };
}

/** Date proposée (ISO ou AAAA-MM-JJ). Vide si le conseil ne la porte pas. */
export function proposedDepartureMs(best) {
  const direct = best?.departIso || best?.departNow;
  if (direct) {
    const t = Date.parse(String(direct).length === 10 ? `${direct}T00:00:00Z` : direct);
    if (Number.isFinite(t)) return t;
  }
  for (const raw of best?.facts || []) {
    const dep = String(raw).match(/^départ (\d{4}-\d{2}-\d{2}) → (\d{4}-\d{2}-\d{2})$/);
    if (dep) {
      const t = Date.parse(`${dep[2]}T00:00:00Z`);
      if (Number.isFinite(t)) return t;
    }
  }
  return null;
}

/** Appliquer est interdit quand la date proposée n'est pas après maintenant. */
export function adviceApplyDisabled(best, now = Date.now()) {
  const when = proposedDepartureMs(best);
  if (!Number.isFinite(when)) return false;
  const t = now instanceof Date ? now.getTime() : Number(now);
  if (!Number.isFinite(t)) return false;
  return when <= t;
}

export function reviewPlan(review, clock, lookup, lang = "fr", opts = {}) {
  const legs = review?.legs || [];
  return legs.map((leg) => reviewLeg(leg, seasonForLeg(leg, clock, lookup), lang, opts));
}

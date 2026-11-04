import { useEffect, useMemo, useState } from "react";
import { nextEtaRetryMs, sleepMs } from "./usePlanReview.js";
import { haversineNm, wrapLon } from "../utils/geo.js";
// A null coordinate is unknown, never 0 (Number(null) === 0).
import { finiteCoord } from "./useMoment.js";

/**
 * A journal moment further than this from the boat does not describe it.
 * A little more than one day of sailing (the journal writes about one moment
 * a day), far less than the distance between two territories.
 */
export const MOMENT_MAX_NM = 200;

const API_URL = import.meta.env?.VITE_API_URL ?? "";

export const MOMENT_JOURNAL_CAP = 2000;
export const MOMENT_JOURNAL_KEY_PREFIX = "naviguide.moment-journal.v1.";

export function momentJournalStorageKey(routeId) {
  return `${MOMENT_JOURNAL_KEY_PREFIX}${String(routeId || "anon")}`;
}

export function journalStorage(storage) {
  if (storage) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function isJournalEntry(row) {
  return Boolean(row && typeof row === "object" && row.t && row.signature);
}

export function sortJournalEntries(entries) {
  return [...(Array.isArray(entries) ? entries : [])].filter(isJournalEntry).sort((a, b) => {
    const ta = Date.parse(a.t);
    const tb = Date.parse(b.t);
    if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return ta - tb;
    return (Number(a.seq) || 0) - (Number(b.seq) || 0);
  });
}

export function visibleJournalEntries(entries, { until } = {}) {
  const rows = sortJournalEntries(entries);
  if (!until) return rows;
  const cut = Date.parse(until);
  if (!Number.isFinite(cut)) return rows;
  return rows.filter((row) => {
    const ms = Date.parse(row.t);
    return !Number.isFinite(ms) || ms <= cut;
  });
}

export function momentAtOrBefore(entries, t) {
  const rows = visibleJournalEntries(entries, { until: t });
  const last = rows[rows.length - 1];
  if (!last) return null;
  return last.moment || last;
}

function entryPos(row) {
  const pos = row?.pos || row?.moment?.pos || null;
  const lat = finiteCoord(pos?.lat);
  const lon = finiteCoord(pos?.lon);
  return pos && Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null;
}

/** Distance (nm) from a journal row to a position, or Infinity. */
export function entryNmFrom(row, at) {
  const p = entryPos(row);
  const lat = finiteCoord(at?.lat);
  const lon = finiteCoord(at?.lon);
  if (!p || !Number.isFinite(lat) || !Number.isFinite(lon)) return Infinity;
  return haversineNm(p.lat, wrapLon(p.lon), lat, wrapLon(lon));
}

/**
 * The journal moment for a position: the nearest one up to `t`, within
 * `maxNm`; among equally near ones, the latest. Never one far away just
 * because its date is the closest. Without a position: by date.
 */
export function momentNearest(entries, { t, pos, maxNm = MOMENT_MAX_NM } = {}) {
  const lat = finiteCoord(pos?.lat);
  const lon = finiteCoord(pos?.lon);
  if (!pos || !Number.isFinite(lat) || !Number.isFinite(lon)) return momentAtOrBefore(entries, t);
  const rows = visibleJournalEntries(entries, { until: t });
  let best = null;
  let bestNm = Infinity;
  for (const row of rows) {
    const nm = entryNmFrom(row, { lat, lon });
    if (nm <= maxNm && nm <= bestNm) {
      best = row;
      bestNm = nm;
    }
  }
  return best ? (best.moment || best) : null;
}

export function parseOfficialMoments(body) {
  const raw = Array.isArray(body?.moments) ? body.moments : (Array.isArray(body) ? body : []);
  return sortJournalEntries(raw);
}

export function slimJournalEntry(row) {
  if (!isJournalEntry(row)) return null;
  const moment = row.moment && typeof row.moment === "object" ? row.moment : row;
  const zeeName = moment.here?.zee?.name;
  const lat = Number(row.pos?.lat ?? moment.pos?.lat);
  const lon = Number(row.pos?.lon ?? moment.pos?.lon);
  return {
    voyageId: row.voyageId || "local",
    seq: Number.isFinite(Number(row.seq)) ? Number(row.seq) : 0,
    t: row.t,
    pos: Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null,
    signature: String(row.signature),
    changes: (Array.isArray(row.changes) ? row.changes : [])
      .filter((c) => c && c.title)
      .map((c) => ({ kind: c.kind || "", score: Number(c.score) || 0, title: String(c.title), fact: String(c.fact || "") })),
    here: zeeName ? { zee: { name: String(zeeName) } } : undefined,
    leg: moment.leg ? { to: moment.leg.to || "", regime: moment.leg.regime || "" } : undefined,
    alerts: (moment.alerts || [])
      .filter((a) => a && a.id)
      .map((a) => ({ id: String(a.id), title: String(a.title || ""), fact: String(a.fact || "") })),
    around: (moment.around || [])
      .filter((item) => item && item.title)
      .map((item) => ({ kind: item.kind || "", title: String(item.title), fact: String(item.fact || "") })),
  };
}

export function readLocalJournal(routeId, storage) {
  const st = journalStorage(storage);
  if (!st) return [];
  try {
    return sortJournalEntries(JSON.parse(st.getItem(momentJournalStorageKey(routeId)) || "[]"));
  } catch {
    return [];
  }
}

export function writeLocalJournal(routeId, entries, storage) {
  const capped = sortJournalEntries(entries).slice(-MOMENT_JOURNAL_CAP).map(slimJournalEntry).filter(Boolean);
  const st = journalStorage(storage);
  if (!st) return capped;
  try {
    st.setItem(momentJournalStorageKey(routeId), JSON.stringify(capped));
    return capped;
  } catch {
    const half = capped.slice(-Math.floor(MOMENT_JOURNAL_CAP / 2));
    try {
      st.setItem(momentJournalStorageKey(routeId), JSON.stringify(half));
    } catch {
      /* quota */
    }
    return half;
  }
}

const NAMED_ALERT_KIND = Object.freeze({ mpa: "amp", amp: "amp", cyclone: "cyclone" });

export function localChanges(prev, cur) {
  if (!prev || !cur) return [];
  const out = [];
  const prevZee = prev.here?.zee?.name;
  const curZee = cur.here?.zee?.name;
  if (curZee && curZee !== prevZee) {
    out.push({ kind: "zee-enter", score: 2, title: String(curZee), fact: "" });
  }
  const prevTo = prev.leg?.to;
  const curTo = cur.leg?.to;
  if (curTo && curTo !== prevTo) {
    out.push({ kind: "escale", score: 3, title: String(curTo), fact: "" });
  }
  const prevMpa = new Set(
    (prev.here?.mpa || []).map((m) => m && (m.site_id || m.name)).filter(Boolean),
  );
  for (const mpa of cur.here?.mpa || []) {
    const key = mpa && (mpa.site_id || mpa.name);
    if (!key || !mpa.name || prevMpa.has(key)) continue;
    const nm = Number(mpa.nm);
    const fact = Number.isFinite(nm) ? `${mpa.name} (${mpa.nm} nm)` : String(mpa.name);
    out.push({ kind: "amp", score: 1, title: String(mpa.name), fact });
  }
  const prevAlerts = new Set((prev.alerts || []).map((a) => a && a.id).filter(Boolean));
  for (const alert of cur.alerts || []) {
    if (alert?.id && alert.title && !prevAlerts.has(alert.id)) {
      const kind = NAMED_ALERT_KIND[alert.kind] || "alert-on";
      if (kind === "amp" && out.some((c) => c.kind === "amp")) continue;
      out.push({ kind, score: 3, title: String(alert.title), fact: String(alert.fact || "") });
    }
  }
  const prevAround = new Set((prev.around || []).map((item) => item && item.title).filter(Boolean));
  for (const item of cur.around || []) {
    if (item?.title && !prevAround.has(item.title)) {
      out.push({ kind: item.kind || "around", score: 1, title: String(item.title), fact: String(item.fact || "") });
    }
  }
  if (prev.leg?.regime && cur.leg?.regime && prev.leg.regime !== cur.leg.regime) {
    out.push({ kind: "regime", score: 1, title: String(cur.leg.regime), fact: "" });
  }
  return out;
}

export function appendLocalMoment(entries, moment, { voyageId = "local" } = {}) {
  const rows = Array.isArray(entries) ? entries : [];
  if (!moment?.signature || !moment?.t) return rows;
  if (rows.some((row) => row.signature === moment.signature)) return rows;
  const ordered = sortJournalEntries(rows);
  const last = ordered[ordered.length - 1];
  const next = {
    voyageId,
    seq: last ? (Number(last.seq) || 0) + 1 : 0,
    t: moment.t,
    pos: moment.pos || null,
    signature: String(moment.signature),
    changes: last ? localChanges(last.moment || last, moment) : [],
    moment,
  };
  return ordered.concat(next).slice(-MOMENT_JOURNAL_CAP);
}

export function momentsRequestPath(voyageId, lang = "fr") {
  const id = String(voyageId || "").trim();
  if (id && id !== "official") return `/voyage/${encodeURIComponent(id)}/moments`;
  return String(lang || "fr").toLowerCase().startsWith("en")
    ? `/voyage/official/moments?lang=${encodeURIComponent(lang)}`
    : "/voyage/official/moments";
}

async function defaultMomentsFetch({ signal, voyageId = "official", lang = "fr" } = {}) {
  const res = await fetch(`${API_URL}${momentsRequestPath(voyageId, lang)}`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * Route perso encore en cours : le serveur rend `preparing` avec un premier
 * morceau tant que coverageNm n'a pas rattrapé totalNm. Le journal officiel
 * est déjà `ready` : un seul GET dès que des lignes sont là.
 */
export function momentsStillPartial(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const status = String(body.status || "").toLowerCase();
  if (!status || status === "ready") return false;
  const coverage = Number(body.coverageNm);
  const total = Number(body.totalNm);
  return Number.isFinite(coverage) && Number.isFinite(total) && coverage < total;
}

/**
 * Berry (Suivre) ne montre que le passé du tour. Suivre × ma route part
 * aujourd'hui : la liste suit toute la traversée. `null` = pas de coupe.
 */
export function journalListUntil({ mode, until, suivreCustom = false } = {}) {
  if (mode !== "follow" || suivreCustom) return null;
  return until ?? null;
}

/**
 * Relance GET /moments tant que la liste est vide, que le fetch a échoué,
 * ou que la route perso est encore partielle (status ≠ ready et
 * coverageNm < totalNm). Les lignes déjà reçues restent affichées.
 * Même recul que pollOfficialEta / nextEtaRetryMs.
 */
export async function pollOfficialMoments({
  fetchFn = defaultMomentsFetch,
  signal,
  sleep = sleepMs,
  onUpdate,
} = {}) {
  let attempt = 0;
  let shown = [];
  while (!signal?.aborted) {
    let body = null;
    let errMsg = null;
    try {
      body = await fetchFn({ signal });
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      body = null;
      errMsg = err?.message || "error";
    }
    const failed = body == null;
    const entries = parseOfficialMoments(body);
    if (entries.length) shown = entries;
    const partial = !failed && momentsStillPartial(body);
    if (shown.length && !failed && !partial) {
      onUpdate?.({ entries: shown, error: null, source: "api" });
      return shown;
    }
    onUpdate?.({
      entries: shown,
      error: shown.length ? null : errMsg,
      source: shown.length ? "api" : "none",
    });
    await sleep(nextEtaRetryMs(attempt), signal);
    attempt += 1;
  }
  return shown;
}

/**
 * Official voyage: GET /voyage/official/moments.
 * Simulation / drawn: localStorage, key = route id, ≤ 2 000, built from Moments.
 */
export function useMomentJournal({
  mode = "follow",
  routeId = "official",
  incomingMoment = null,
  until = null,
  enabled = true,
  suivreCustom = false,
  lang = "fr",
} = {}) {
  const local = mode === "simulation" || mode === "drawn";
  const [state, setState] = useState(() => ({
    entries: local ? readLocalJournal(routeId) : [],
    loading: false,
    error: null,
    source: local ? "local" : "none",
  }));

  useEffect(() => {
    if (!enabled) return undefined;
    if (local) {
      setState({
        entries: readLocalJournal(routeId),
        loading: false,
        error: null,
        source: "local",
      });
      return undefined;
    }
    const controller = new AbortController();
    let alive = true;
    setState({ entries: [], loading: true, error: null, source: "none" });
    pollOfficialMoments({
      fetchFn: (opts) => defaultMomentsFetch({ ...opts, voyageId: routeId, lang }),
      signal: controller.signal,
      onUpdate: (next) => {
        if (!alive) return;
        setState({
          entries: next.entries,
          loading: false,
          error: next.error,
          source: next.source,
        });
      },
    }).catch((err) => {
      if (!alive || err?.name === "AbortError") return;
      setState({
        entries: [],
        loading: false,
        error: err?.message || "error",
        source: "none",
      });
    });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [enabled, local, routeId, lang]);

  useEffect(() => {
    if (!enabled || !local || !incomingMoment?.signature) return;
    setState((prev) => {
      const next = appendLocalMoment(prev.entries, incomingMoment, { voyageId: routeId });
      if (next === prev.entries) return prev;
      return {
        ...prev,
        entries: writeLocalJournal(routeId, next),
        source: "local",
        error: null,
      };
    });
  }, [enabled, local, routeId, incomingMoment]);

  const entries = useMemo(
    () => visibleJournalEntries(state.entries, {
      until: journalListUntil({ mode, until, suivreCustom }),
    }),
    [state.entries, mode, until, suivreCustom],
  );
  const nowMoment = useMemo(
    () => (mode === "follow" ? momentAtOrBefore(state.entries, until) : null),
    [state.entries, mode, until],
  );

  return {
    entries,
    nowMoment,
    loading: state.loading,
    error: state.error,
    source: state.source,
  };
}

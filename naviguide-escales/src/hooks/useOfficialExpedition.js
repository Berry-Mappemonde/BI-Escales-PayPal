import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_T0_ISO, OFFICIAL_VOYAGE_ID, sampleClockAtTime } from "../engine/voyageClock.js";
import { pickOfficialLiveClock } from "../utils/sceneGate.js";
import { adminHeaders, hasAdminSecret } from "../utils/adminSecret.js";
import { officialGribQuery, officialGribStatus, officialGribWarning } from "./gribStatus.js";

const API = import.meta.env?.VITE_API_URL ?? "";

/** Relances de la lecture de l'horloge officielle tant qu'elle n'est pas arrivée : 5 s, 10, 20, 40, puis 60 s. */
export const OFFICIAL_RETRY_MS = [5000, 10000, 20000, 40000, 60000];

export function officialRetryDelayMs(attempt) {
  const i = Number.isFinite(attempt) && attempt > 0 ? Math.min(Math.floor(attempt), OFFICIAL_RETRY_MS.length) : 1;
  return OFFICIAL_RETRY_MS[i - 1];
}

/** A client clock is "official" when it starts on the expedition's fixed t0. */
export function isOfficialClock(clock) {
  const t0 = Date.parse(clock?.t0 ?? "");
  return Number.isFinite(t0) && t0 === Date.parse(DEFAULT_T0_ISO);
}

/** A t0-only "preparing" response is not a usable live clock. */
export function isUsableOfficialClock(clock) {
  return isOfficialClock(clock) && Array.isArray(clock?.vertices) && clock.vertices.length > 1;
}

/**
 * Voyage officiel unique. Pas de localStorage visiteur.
 * Position = horloge serveur à maintenant (1 s = 1 s), avec repli figé
 * sur le premier snapshot client si le PUT officiel n’a pas encore répondu
 * (404 après redémarrage, 502 de deploy, calcul _climo_clock lent).
 * Dernier GRIB = overlay vent, jamais un nouveau trait, jamais de climatologie.
 */
export function useOfficialExpedition({
  enabled,
  points,
  marks,
  expeditionId,
  clock,
}) {
  const [meta, setMeta] = useState(null);
  const [serverClock, setServerClock] = useState(null);
  const [grib, setGrib] = useState(null);
  const [gribPending, setGribPending] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [clockStatus, setClockStatus] = useState("pending");
  const putRef = useRef("");
  const serverClockRef = useRef(serverClock);
  const frozenClientRef = useRef(null);
  serverClockRef.current = serverClock;

  useEffect(() => {
    if (!enabled) return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !points?.length) frozenClientRef.current = null;
  }, [enabled, points]);

  const liveClock = useMemo(() => {
    // Only an official clock (t0 = 15 May) may stand in for the server. A
    // Simulation clock (t0 = today) frozen here put the boat back at
    // Saint-Maur on day 0 — never freeze while Suivre is off.
    if (!enabled) {
      frozenClientRef.current = null;
      return null;
    }
    const officialClient = isOfficialClock(clock) ? clock : null;
    if (serverClock) {
      frozenClientRef.current = frozenClientRef.current || officialClient;
      return serverClock;
    }
    // Pas de cache client tant que le serveur n'a pas répondu : sinon saut Nouméa → Panama.
    if (clockStatus !== "absent") return null;
    const picked = pickOfficialLiveClock(null, officialClient, frozenClientRef.current);
    frozenClientRef.current = picked.frozenClient;
    return picked.liveClock;
  }, [enabled, serverClock, clock, clockStatus]);

  const putOfficial = useCallback(async () => {
    if (!points?.length) return null;
    const fp = `${points.length}|${points[0]?.lat}|${points[points.length - 1]?.lat}|${expeditionId || ""}`;
    if (putRef.current === fp && meta?.voyageId === OFFICIAL_VOYAGE_ID) return meta;
    // Anonymous: the server only creates a missing official voyage, never
    // edits it. With the admin key (X-Naviguide-Admin) it may update the route.
    const res = await fetch(`${API}/voyage/official`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({
        t0: DEFAULT_T0_ISO,
        expedition_id: expeditionId || "berry-mappemonde-2026",
        routeKind: "berry",
        follow: true,
        forecast: false,
        startAt: "la-rochelle",
        official: true,
        points: points.map((p) => ({
          lat: p.lat,
          lon: p.lon,
          cumNm: p.cumNm,
          filmCum: p.filmCum,
          jump: Boolean(p.jump),
          nonMaritime: Boolean(p.nonMaritime),
          air: Boolean(p.air),
        })),
        marks: (marks || []).map((m) => ({
          name: m.name,
          nm: m.nm,
          filmNm: m.filmNm,
          lat: m.lat,
          lon: m.lon,
          index: m.index,
          flag: true,
        })),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return null;
    putRef.current = fp;
    setMeta(data);
    if (isUsableOfficialClock(data.clock)) {
      setServerClock(data.clock);
      setClockStatus("ready");
    }
    return data;
  }, [points, marks, expeditionId, meta]);

  // Une seule lecture de l'horloge à la fois. 29 sept. (poste derrière le tunnel) : la réponse
  // /voyage/official/clock pèse 3,9 Mo et le PUT /voyage/official la porte aussi ; la relance toutes les 5 s
  // repartait sans attendre la précédente — 134 requêtes en 4 min, 50 téléchargements de l'horloge en vol,
  // le tunnel saturé, l'horloge jamais arrivée : le bateau restait au jour 0 et Revoir grisé.
  const inflightRef = useRef(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    if (!enabled || !points?.length) return undefined;
    let cancelled = false;
    let timer = null;
    const readClock = () => fetch(`${API}/voyage/official/clock`)
      .then((r) => {
        if (r.ok) return r.json();
        if (!cancelled && (r.status === 404 || r.status >= 500)) setClockStatus("absent");
        return null;
      })
      .then((ck) => {
        if (isUsableOfficialClock(ck) && !cancelled) {
          setServerClock(ck);
          setClockStatus("ready");
          return ck;
        }
        // HTTP 200 status=preparing (t0 sans vertices) : pas une horloge utilisable.
        // On ne touche pas à clockStatus (un repli figé déjà affiché reste) ; c'est
        // gotClock (plus bas) qui fait continuer la relance espacée.
        return null;
      })
      .catch(() => { if (!cancelled) setClockStatus("absent"); return null; });
    const kick = async () => {
      if (cancelled) return;
      if (inflightRef.current) {
        // Une paire GET / PUT est déjà en vol (autre rendu du hook) : on repasse plus tard, on n'empile pas.
        timer = setTimeout(kick, 2000);
        return;
      }
      inflightRef.current = true;
      let gotClock = false;
      try {
        // Lire l'horloge avant d'envoyer le PUT : une visite normale n'a pas besoin de renvoyer
        // le gros voyage au serveur. Le PUT reste nécessaire pour une mise à jour admin ou pour
        // réparer une horloge absente/inutilisable (notamment un corps « preparing » avec seulement t0).
        const haveClock = Boolean(serverClockRef.current);
        const ck = haveClock ? null : await readClock();
        // Une annulation de l'effet ne doit pas empêcher la réparation après un GET 404 :
        // le PUT est aussi ce qui crée l'horloge officielle manquante.
        const needPut = hasAdminSecret() || (!haveClock && !isUsableOfficialClock(ck));
        const data = needPut ? await putOfficial().catch(() => null) : null;
        if (cancelled) return;
        gotClock = haveClock || isUsableOfficialClock(ck) || isUsableOfficialClock(data?.clock);
      } finally {
        inflightRef.current = false;
      }
      if (cancelled) return;
      if (gotClock || serverClockRef.current) {
        attemptRef.current = 0;
        return;
      }
      attemptRef.current += 1;
      timer = setTimeout(kick, officialRetryDelayMs(attemptRef.current));
    };
    kick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [enabled, points, putOfficial]);

  const refreshGrib = useCallback(async ({ force = false } = {}) => {
    const q = officialGribQuery(serverClockRef.current);
    if (!q) return null;
    const qs = `?lat=${encodeURIComponent(q.lat)}&lon=${encodeURIComponent(q.lon)}`;
    const url = force ? `${API}/voyage/official/grib/refresh${qs}` : `${API}/voyage/official/grib${qs}`;
    const res = await fetch(url, force ? { method: "POST", headers: adminHeaders() } : undefined);
    const data = await res.json().catch(() => null);
    if (res.ok && data) {
      setGrib(data);
      setGribPending(data.status === "pending" || Boolean(data.refreshing));
    }
    return data;
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const q = officialGribQuery(serverClock);
    if (!q) {
      setGribPending(true);
      return undefined;
    }
    let cancelled = false;
    let retry = null;
    setGribPending(true);
    const refresh = () => {
      refreshGrib()
        .then((data) => {
          if (!cancelled && (data?.status === "pending" || data?.refreshing)) {
            clearTimeout(retry);
            retry = setTimeout(refresh, 4000);
          }
        })
        .catch(() => {
          if (!cancelled) setGribPending(false);
        });
    };
    refresh();
    const id = setInterval(() => {
      refresh();
    }, 60_000);
    return () => {
      cancelled = true;
      clearTimeout(retry);
      clearInterval(id);
    };
  }, [enabled, refreshGrib, meta?.voyageId, serverClock]);

  const live = useMemo(() => {
    if (!enabled || !liveClock) return null;
    const sample = sampleClockAtTime(liveClock, new Date(nowMs));
    if (!sample) return null;
    const wind = grib?.wind;
    const regime = sample.regime || sample.kind || "climatology";
    if (grib?.status === "ready" && wind) {
      const models = (grib.products || [])
        .filter((p) => p.status === "ready")
        .map((p) => p.model);
      return {
        ...sample,
        regime,
        sources: sample.sources || [],
        spread: sample.spread ?? null,
        kind: "forecast",
        model: models[0] || grib.model || wind.model || "GFS",
        waveModel: grib.waveModel || wind.waveModel || null,
        currentModel: grib.currentModel || wind.currentModel || null,
        windKnots: wind.windKnots,
        dirFromDeg: wind.dirFromDeg,
        pressHpa: wind.pressHpa,
        rainMm: wind.rainMm,
        hs: wind.hs,
        gribStatus: "ready",
        gribWarning: null,
      };
    }
    return {
      ...sample,
      regime,
      sources: sample.sources || [],
      spread: sample.spread ?? null,
      kind: "absent",
      model: null,
      windKnots: null,
      dirFromDeg: null,
      gribStatus: grib?.status === "ready" ? "ready" : (gribPending || !grib ? "pending" : "absent"),
      gribWarning: null,
    };
  }, [enabled, liveClock, nowMs, grib, gribPending]);

  const positioned = Boolean(
    liveClock
    && sampleClockAtTime(liveClock, new Date(nowMs))?.lat != null,
  );
  const gribStatus = officialGribStatus({
    enabled,
    grib,
    pending: gribPending,
    positioned,
  });

  return {
    voyageId: OFFICIAL_VOYAGE_ID,
    voyage: meta,
    clock: serverClock,
    live,
    grib,
    gribStatus,
    gribModel: (grib?.products || [])
      .filter((p) => p.status === "ready")
      .map((p) => p.model)
      .filter(Boolean)
      .join(" · ") || grib?.model || null,
    gribWarning: officialGribWarning({ enabled, status: gribStatus }),
    refreshGrib,
  };
}

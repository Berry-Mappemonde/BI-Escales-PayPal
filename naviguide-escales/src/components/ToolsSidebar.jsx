import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fetchWatchSettings, saveWatchSettings } from "../utils/watchSettings.js";
import { CheckCircle2, ChevronLeft, ChevronRight, KeyRound, Loader2, Moon, Sun, TriangleAlert, Upload } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { adminHeaders, getAdminSecret, setAdminSecret } from "../utils/adminSecret.js";
import { SkipperOrdersPanel } from "./SkipperOrdersPanel.jsx";
import { EscaleLegend } from "./EscaleLegend.jsx";
import { DepartureField } from "./DepartureField.jsx";
import { LayerToggles, activeLayerCount } from "./LayerToggles.jsx";
import { drawingRefusalPhrase } from "../hooks/useRouteDrawing.js";
import { summarizeLegs, wrapLon } from "../utils/geo.js";
import { summarizeAmpTraffic } from "../engine/ampRules.js";
import { polarBoatSpeed } from "../engine/polarSpeed.js";
import { buildGeoJSON, buildKML, canExportRoute, downloadFile, exportFilename } from "../utils/routeExport.js";

const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? "";
const POLAR_EXPEDITION = "berry-mappemonde-2026"; // pragma: allowlist secret
const POLAR_VMG_TWS_KEYS = ["8", "10", "12", "16", "20", "25"];
const POLAR_SPEED_TWA = [60, 75, 90, 120, 150];
const POLAR_SPEED_TWS = [8, 10, 12, 16, 20];
const POLAR_FOLD_KEY = "naviguide.tools.polarOpen";
const LAYERS_FOLD_KEY = "naviguide.tools.layersOpen";

function readSessionOpen(key, fallback) {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === "1") return true;
    if (raw === "0") return false;
  } catch {
    /* private mode */
  }
  return fallback;
}

function writeSessionOpen(key, open) {
  try {
    sessionStorage.setItem(key, open ? "1" : "0");
  } catch {
    /* private mode */
  }
}

function layersFoldKey(tracerLayout) {
  return tracerLayout ? `${LAYERS_FOLD_KEY}.tracer` : `${LAYERS_FOLD_KEY}.follow`;
}

/**
 * Polar in Tracer stays a real `<details>` (DM9 / RD3 read `tagName`
 * then `el.open`). React 19 restores `open` from props on `toggle`, so we
 * prevent the native summary toggle and set the IDL after the event.
 */
function FoldDetails({ testId, storageKey, fallbackOpen, className, children }) {
  const [open, setOpen] = useState(() => readSessionOpen(storageKey, fallbackOpen));
  const nodeRef = useRef(null);

  useLayoutEffect(() => {
    const el = nodeRef.current;
    if (!el) return undefined;
    el.open = open;
    const summary = el.querySelector("summary");
    const onClick = (e) => {
      e.preventDefault();
      setOpen((v) => {
        const next = !v;
        writeSessionOpen(storageKey, next);
        return next;
      });
    };
    summary?.addEventListener("click", onClick, true);
    return () => summary?.removeEventListener("click", onClick, true);
  });

  return (
    <details ref={nodeRef} className={className} data-testid={testId} open={open}>
      {children}
    </details>
  );
}

/**
 * Calques cannot be a `<details>`: React 19's toggle restore keeps
 * `el.open` false even when we want it déplié in Tracer. A `div` with the
 * same test id, a `<summary>`, and an IDL `open` flag matches the recette
 * without fighting the host component.
 */
function LayersDrawer({ tracerLayout, layersOn, t, maritimeLayers }) {
  const [open, setOpen] = useState(() => (
    readSessionOpen(layersFoldKey(tracerLayout), Boolean(tracerLayout))
  ));
  const nodeRef = useRef(null);

  return (
    <div
      ref={(el) => {
        nodeRef.current = el;
        if (el) el.open = open;
      }}
      className="px-4 py-3 border-t border-slate-700/60 group"
      data-testid="layers-drawer"
    >
      <summary
        className="cursor-pointer select-none list-none flex items-center justify-between gap-2"
        onClick={() => {
          setOpen((v) => {
            const next = !v;
            writeSessionOpen(layersFoldKey(tracerLayout), next);
            return next;
          });
        }}
        data-tour="layers"
      >
        <span className="text-[11px] font-semibold text-slate-200">{t("layersTitle")}</span>
        <span className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">{layersOn ? t("layersOn", { n: layersOn }) : t("layersNone")}</span>
          <span className={`text-slate-500 transition-transform ${open ? "rotate-90" : ""}`}>›</span>
        </span>
      </summary>
      {open ? (
        <div className="mt-2">
          <LayerToggles maritimeLayers={maritimeLayers} />
        </div>
      ) : null}
    </div>
  );
}

function kts(v) { return v != null ? `${Number(v).toFixed(1)} kt` : "—"; }
function deg(v) { return v != null ? `${Math.round(v)}°` : "—"; }

/** Même arrondi que GET /api/v1/polar/{id}/speed (3 décimales). */
function formatPolarKn(kn, lang) {
  if (!Number.isFinite(kn)) return "—";
  const s = String(Math.round(kn * 1000) / 1000);
  return lang === "en" ? `${s} kn` : `${s.replace(".", ",")} kn`;
}

function PolarSpeedGrid({ raw, lang }) {
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-slate-700/40 bg-slate-900/40" data-testid="polar-table">
      <table className="w-full text-[10px]">
        <thead>
          <tr className="bg-slate-800/80 border-b border-slate-700/60">
            <th className="py-1 px-1 text-left text-slate-300">TWA</th>
            {POLAR_SPEED_TWS.map((tws) => (
              <th key={tws} className="py-1 px-1 text-center text-slate-300">{tws}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {POLAR_SPEED_TWA.map((twa) => (
            <tr key={twa} className="border-b border-slate-700/40">
              <th className="py-1 px-1 text-left font-semibold text-slate-200">{twa}°</th>
              {POLAR_SPEED_TWS.map((tws) => {
                const kn = polarBoatSpeed(raw, twa, tws);
                return (
                  <td
                    key={tws}
                    data-testid={`polar-speed-${twa}-${tws}`}
                    data-kn={Number.isFinite(kn) ? String(kn) : ""}
                    className="py-1 px-1 text-center text-slate-200"
                  >
                    {formatPolarKn(kn, lang)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

async function readPolarResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    // A proxy failure may have an HTML response rather than JSON.
  }
  if (response.ok) return data;

  const error = new Error(data?.detail ?? `HTTP ${response.status}`);
  error.status = response.status;
  error.detail = data?.detail;
  throw error;
}

export function polarErrorDetail(error, t) {
  if (error?.code === "DEFAULT_POLAR_NOT_FOUND") return t("polarDefaultUnavailable");
  if (error?.status === 401 || error?.status === 503) return t("adminKeyRequired");
  if (error?.status === 413) return t("polarFileTooLarge");
  if (error?.status >= 500) return t("polarServiceUnavailable");
  // Server details may contain internal codes or exception text.
  return t("polarNetworkError");
}

function PolarVmgRow({ tws, entry }) {
  const uw = entry?.upwind ?? {};
  const dw = entry?.downwind ?? {};
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition-colors">
      <td className="py-1 pl-2 pr-1 text-center font-bold text-blue-300 text-xs w-8">{tws}</td>
      <td className="py-1 px-1 text-center text-xs text-green-300">{deg(uw.twa)}</td>
      <td className="py-1 px-1 text-center text-xs text-slate-200">{kts(uw.speed)}</td>
      <td className="py-1 px-1 text-center text-xs font-semibold text-green-400">{kts(uw.vmg)}</td>
      <td className="py-1 px-0.5 text-slate-600 text-center text-xs">│</td>
      <td className="py-1 px-1 text-center text-xs text-amber-300">{deg(dw.twa)}</td>
      <td className="py-1 px-1 text-center text-xs text-slate-200">{kts(dw.speed)}</td>
      <td className="py-1 pr-2 pl-1 text-center text-xs font-semibold text-amber-400">{kts(dw.vmg)}</td>
    </tr>
  );
}

/**
 * Sécurité P0 — la clé admin partagée (X-Naviguide-Admin), sur une ligne :
 * icône, champ « Coller la clé admin », OK. Stockée dans ce navigateur.
 */
function TavilyWatchToggle() {
  const { t } = useLang();
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => {
    let live = true;
    fetchWatchSettings()
      .then((s) => { if (live && s) setEnabled(s.enabled); })
      .catch(() => { if (live) setNote("tavilyWatchError"); });
    return () => { live = false; };
  }, []);
  const flip = async () => {
    if (enabled === null || busy) return;
    setBusy(true);
    const out = await saveWatchSettings(!enabled);
    setBusy(false);
    if (out.ok) {
      setEnabled(out.settings.enabled);
      setNote("");
    } else {
      setNote(out.reason === "admin" ? "tavilyWatchAdmin" : "tavilyWatchError");
    }
  };
  const on = Boolean(enabled);
  return (
    <div className="rounded-xl border border-slate-700/40 bg-slate-800/40 px-3 py-2" data-testid="tavily-watch-setting">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0">
          <span id="tavily-watch-label" className="block text-xs font-medium text-slate-200">{t("tavilyWatchLabel")}</span>
          <span id="tavily-watch-hint" className="block text-[10px] leading-snug text-slate-400">{t("tavilyWatchHint")}</span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby="tavily-watch-label"
          aria-describedby="tavily-watch-hint"
          data-testid="tavily-watch-toggle"
          data-state={enabled === null ? "unknown" : on ? "on" : "off"}
          disabled={enabled === null || busy}
          onClick={flip}
          className={`w-10 h-5 rounded-full relative flex-shrink-0 transition-colors disabled:opacity-50 ${on ? "bg-violet-500" : "bg-slate-600"}`}
        >
          <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${on ? "left-5" : "left-0.5"}`} />
        </button>
      </div>
      {note ? <p role="status" data-testid="tavily-watch-note" className="mt-1 text-[10px] leading-snug text-amber-300/90">{t(note)}</p> : null}
    </div>
  );
}

function AdminKeyField() {
  const { t } = useLang();
  const [value, setValue] = useState(() => getAdminSecret());
  const [saved, setSaved] = useState(() => Boolean(getAdminSecret()));
  const commit = () => {
    setAdminSecret(value);
    setSaved(Boolean(value.trim()));
  };
  return (
    <div className="flex items-center gap-1.5" data-testid="admin-key">
      <KeyRound size={13} className={saved ? "text-emerald-400 flex-shrink-0" : "text-slate-500 flex-shrink-0"} title={saved ? t("adminKeyActive") : t("adminKeyLabel")} />
      <input
        name="admin-key"
        type="password"
        autoComplete="off"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
        placeholder={t("adminKeyPlaceholder")}
        aria-label={t("adminKeyLabel")}
        className="flex-1 min-w-0 bg-slate-900/70 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-200 placeholder:text-slate-500"
      />
      <button
        type="button"
        onClick={commit}
        className="px-2 py-1 rounded-lg text-xs font-semibold bg-slate-700 hover:bg-slate-600 text-slate-100"
      >
        {t("adminKeySave")}
      </button>
    </div>
  );
}

async function polarMetaFromUpload(data) {
  let raw = data.raw;
  if (!raw?.twa_rows && data.expedition_id) {
    try {
      const res = await fetch(`${POLAR_API_URL}/api/v1/polar/${encodeURIComponent(data.expedition_id)}`);
      if (res.ok) {
        const full = await res.json();
        raw = full.raw;
      }
    } catch {
      raw = null;
    }
  }
  return {
    expedition_id: data.expedition_id,
    boat_name: data.boat_name,
    grid_shape: data.grid_shape,
    vmg_summary: data.vmg_summary,
    created_at: data.created_at,
    raw: raw || null,
  };
}

function Toggle({ labelLeft, labelRight, active, onChange }) {
  const label = active ? labelRight : labelLeft;
  return (
    <button
      type="button"
      onClick={() => onChange(!active)}
      aria-label={label}
      aria-pressed={active}
      title={label}
      className={`w-10 h-5 rounded-full relative transition-colors ${active ? "bg-sky-500" : "bg-slate-600"}`}
    >
      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${active ? "left-5" : "left-0.5"}`} />
      <span className="sr-only">{label}</span>
      <span aria-hidden="true" className={`absolute top-1 ${active ? "left-1" : "right-1"} text-white/90`}>
        {active ? <Sun size={11} /> : <Moon size={11} />}
      </span>
    </button>
  );
}

function SectionTitle({ children, right = null }) {
  return (
    <div className="flex items-center justify-between gap-2 mb-1">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{children}</span>
      {right}
    </div>
  );
}

/**
 * The whole expedition, compact: the route in numbers on two lines and the
 * stopovers list (click = jump). Revue du 19 sept. : one box, not two.
 */
/** While the skipper draws, the box describes the drawn route, not the official one. */
function DrawingBox({ drawing }) {
  const { t } = useLang();
  const pts = drawing?.points || [];
  const refusal = drawingRefusalPhrase(drawing?.notice, t);
  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/30 overflow-hidden" data-testid="drawing-box">
      <div className="px-3 py-1.5 text-[10px] text-slate-200 leading-snug flex flex-wrap gap-x-2 gap-y-0.5" data-testid="drawing-summary">
        <span className="font-semibold text-emerald-200">{t("drawingInProgress")}</span>
        <span>· {pts.length} {t("drawingPoints")}</span>
        <span>· {Number(drawing?.distanceNm || 0).toLocaleString()} nm</span>
      </div>
      {refusal ? (
        <p className="px-3 py-1 text-[10px] leading-snug text-rose-100 border-t border-white/5">{refusal}</p>
      ) : null}
      {pts.length ? (
        <ol className="max-h-36 overflow-y-auto sidebar-scroll border-t border-white/5">
          {pts.map((p, i) => (
            <li key={`${p.lat}-${p.lon}-${i}`} className="px-2 py-1 text-[11px] text-white/80 border-t border-white/5 first:border-t-0 flex items-baseline gap-1">
              <span className="text-[9px] text-emerald-300/80 w-4 shrink-0">{i + 1}</span>
              <span className="truncate">{p.name}</span>
              <span className="ml-auto text-[9px] text-white/40 tabular-nums shrink-0">{p.lat.toFixed(2)}° · {wrapLon(p.lon).toFixed(2)}°</span>
            </li>
          ))}
        </ol>
      ) : refusal ? null : (
        <p className="px-3 pb-2 text-[10px] text-slate-400 leading-snug">{drawing?.message || t("drawStart")}</p>
      )}
    </div>
  );
}

function ExpeditionBox({ routeDistanceNm, routeSegmentCount, routeCounts, waypointCount, escaleMarks, filmNm, onSeekEscale, onEscaleSheet, drawing = null, segments = [], frozen = false, nowMs, liveFilmNm, officialEta = false, ampNearby = [] }) {
  const { t, lang } = useLang();
  const locale = lang === "fr" ? "fr-FR" : "en-US";
  const ampTraffic = summarizeAmpTraffic(ampNearby, lang);
  const nm = routeDistanceNm != null ? `${Number(routeDistanceNm).toLocaleString(locale)} nm` : "—";
  const lastMark = escaleMarks?.length ? escaleMarks[escaleMarks.length - 1] : null;
  const filmAxis = lastMark != null ? Number(lastMark.filmNm ?? lastMark.nm) : null;
  const totalHint = routeDistanceNm != null
    ? Number(routeDistanceNm).toLocaleString(locale)
    : (Number.isFinite(filmAxis) ? filmAxis.toLocaleString(locale) : "—");
  const distanceHint = t("routeDistanceHint", { total: totalHint });
  const summary = summarizeLegs(escaleMarks, segments);
  const routerWaypoints = waypointCount ?? routeSegmentCount ?? summary.waypoints;
  const vertexCount = summary.points || routeCounts?.points || 0;
  const legsWord = summary.legs === 1 ? t("routeLegOne") : t("routeLegsShort");
  const escalesWord = summary.escales === 1 ? t("routeEscaleOne") : t("routeEscalesShort");
  const pointsHint = t("routePointsHint", {
    waypoints: Number(routerWaypoints).toLocaleString(locale),
    points: Number(vertexCount).toLocaleString(locale),
  });
  // Dessin ouvert : le cadre « Tracé en cours » est toujours là (c'est le retour
  // visuel « vous dessinez, cliquez sur la carte » — surface de main, specs RH2 /
  // R9a / R13 / RF1 / S). DM6 ouvre le dessin dès l'entrée en Tracer : à brouillon
  // vide, la légende des escales reste DESSOUS (vitrine Berry) ; dès le
  // premier point, le cadre remplace l'expédition comme avant DM6.
  if (drawing?.points?.length) return <DrawingBox drawing={drawing} />;
  return (
    <div className="space-y-2">
    {drawing ? <DrawingBox drawing={drawing} /> : null}
    <div className="rounded-xl border border-slate-700/40 bg-slate-800/40 overflow-hidden" data-testid="expedition-box">
      <div className="px-3 py-1.5 text-[10px] text-slate-300 leading-snug flex flex-wrap gap-x-2 gap-y-0.5" data-testid="route-summary" title={distanceHint}>
        <span className="font-semibold text-white cursor-help border-b border-dotted border-white/30" title={distanceHint}>{nm}</span>
        <span>· {summary.legs} {legsWord} ({summary.sea} {t("routeSeaShort")}, {summary.land} {t("routeLandShort")})</span>
        <span>· {summary.escales} {escalesWord}</span>
        <span className="cursor-help border-b border-dotted border-white/30" title={pointsHint}>
          · {vertexCount.toLocaleString(locale)} {t("routePointsShort")}
        </span>
      </div>
      {ampTraffic.line ? (
        <div
          data-testid="amp-traffic-line"
          className={`px-3 py-1 text-[10px] leading-snug border-t ${
            ampTraffic.kind === "forbidden-inside"
              ? "border-rose-500/30 text-rose-200 bg-rose-950/30"
              : "border-amber-500/30 text-amber-100 bg-amber-950/20"
          }`}
        >
          {ampTraffic.line}
        </div>
      ) : null}
      <EscaleLegend marks={escaleMarks} filmNm={filmNm} frozen={frozen} nowMs={nowMs} liveFilmNm={liveFilmNm} officialEta={officialEta} />
    </div>
    </div>
  );
}

export const ToolsSidebar = memo(function ToolsSidebar({
  segments, points, open, onToggle,
  isLightMode, onLightModeChange,
  polarData, onPolarDataLoaded,
  routeDistanceNm, routeSegmentCount,
  maritimeLayers = null,
  escaleMarks = [], filmNm = 0, onSeekEscale, onEscaleSheet, drawing = null, frozen = false,
  nowMs, liveFilmNm, officialEta = false,
  showDeparture = false, departureT0, onDepartureT0,
  skipperOrders = null, skipperProfile = "cruise", onSkipperProfile, onSkipperReset,
  onSkipperComfort, onSkipperHorizon, onSkipperExpert, onSkipperBoat,
  skipperSuggest = null, onSkipperSuggestAccept, onSkipperSuggestDismiss,
  exportMode = "simulation", exportSegments = null, exportPoints = null,
  tracerLayout = false,
  ampNearby = [],
}) {
  const { lang, switchLang, t } = useLang();
  const [polarFile, setPolarFile] = useState(null);
  const [polarUploadStatus, setPolarUploadStatus] = useState(null);
  const [polarUploadDetail, setPolarUploadDetail] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [showPolar, setShowPolar] = useState(false);
  const polarFileInputRef = useRef(null);
  const defaultLoadAttemptedRef = useRef(false);
  const userDroppedFileRef = useRef(false);

  useEffect(() => {
    if (polarFile) handlePolarUpload(polarFile);
  }, [polarFile]);

  useEffect(() => {
    if (polarData || defaultLoadAttemptedRef.current) return;
    defaultLoadAttemptedRef.current = true;
    const loadDefaultPolars = async () => {
      setPolarUploadStatus("uploading");
      try {
        const storedRes = await fetch(
          `${POLAR_API_URL}/api/v1/polar/${encodeURIComponent(POLAR_EXPEDITION)}/client`,
        );
        if (storedRes.ok) {
          const stored = await readPolarResponse(storedRes);
          if (userDroppedFileRef.current) return;
          onPolarDataLoaded(await polarMetaFromUpload(stored));
          setPolarUploadStatus("success");
          setPolarUploadDetail(stored.boat_name);
          return;
        }
        if (storedRes.status !== 404) {
          await readPolarResponse(storedRes);
        }
        const error = new Error("Default polar was not found.");
        error.code = "DEFAULT_POLAR_NOT_FOUND";
        throw error;
      } catch (err) {
        if (userDroppedFileRef.current) return;
        setPolarUploadStatus("error");
        setPolarUploadDetail(polarErrorDetail(err, t));
      }
    };
    loadDefaultPolars();
  }, [polarData, onPolarDataLoaded, t]);

  const handlePolarUpload = async (f) => {
    setPolarUploadStatus("uploading");
    setPolarUploadDetail("");
    const form = new FormData();
    form.append("file", f);
    form.append("expedition_id", POLAR_EXPEDITION);
    try {
      const res = await fetch(`${POLAR_API_URL}/api/v1/polar/upload`, {
        method: "POST",
        headers: adminHeaders(),
        body: form,
      });
      const data = await readPolarResponse(res);
      onPolarDataLoaded(await polarMetaFromUpload(data));
      setPolarUploadStatus("success");
      setPolarUploadDetail(data.boat_name);
    } catch (err) {
      setPolarUploadStatus("error");
      setPolarUploadDetail(polarErrorDetail(err, t));
    }
  };

  const routeCounts = useMemo(() => {
    const maritime = segments.filter((s) => !s.nonMaritime && s.coords?.length > 0);
    const overland = segments.filter((s) => s.nonMaritime && s.coords?.length > 0);
    return {
      maritime: maritime.length,
      overland: overland.length,
      total: maritime.length + overland.length,
      points: segments.reduce((count, segment) => count + (segment.coords?.length ?? 0), 0),
    };
  }, [segments]);

  const polarStatus = polarUploadStatus === "uploading"
    ? { icon: <Loader2 size={12} className="animate-spin" />, color: "text-blue-300", text: t("polarAnalyzing") }
    : polarUploadStatus === "error"
      ? { icon: <TriangleAlert size={12} />, color: "text-red-300", text: `${t("polarFailed")} — ${polarUploadDetail}` }
      : polarData
        ? { icon: <CheckCircle2 size={12} />, color: "text-emerald-300", text: t("polarLoaded") }
        : { icon: <Upload size={12} />, color: "text-slate-400", text: t("polarSection") };
  const layersOn = activeLayerCount(maritimeLayers);
  const routeSegs = exportSegments ?? segments;
  const routePts = exportPoints ?? points;
  const canExport = canExportRoute(routeSegs, routePts);
  const kmlTitle = canExport
    ? (exportMode === "suivre" ? t("exportKmlFollow") : t("exportKML"))
    : t("exportNeedsRoute");
  const geoTitle = canExport ? t("exportGeoJSON") : t("exportNeedsRoute");
  const handleExportGeoJSON = () => {
    if (!canExport) return;
    const fc = buildGeoJSON(routeSegs, routePts, `naviguide-${exportMode}`);
    downloadFile(JSON.stringify(fc, null, 2), exportFilename(exportMode, "geojson"), "application/geo+json");
  };
  const handleExportKML = () => {
    if (!canExport) return;
    const kml = buildKML(routeSegs, routePts, `naviguide-${exportMode}`);
    downloadFile(kml, exportFilename(exportMode, "kml"), "application/vnd.google-earth.kml+xml");
  };

  return (
    <>
      <button
        onClick={onToggle}
        className={`naviguide-sidebar-toggle naviguide-sidebar-toggle--right absolute top-4 z-30 bg-slate-900/95 text-white
          rounded-full w-9 h-9 flex items-center justify-center shadow-lg
          border border-slate-700
          hover:bg-slate-800 transition-all duration-300 ${open ? "right-[322px]" : "right-4"}`}
        aria-label={open ? t("hideToolsPanel") : t("showToolsPanel")}
        title={open ? t("hideToolsPanel") : t("showToolsPanel")}
      >
        {open ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>

      <div
        className={`naviguide-sidebar-panel absolute top-0 right-0 h-full z-20 flex flex-col bg-slate-900/97
          border-l-2 border-sky-400/40 shadow-2xl transition-transform duration-300
          ${open ? "translate-x-0" : "translate-x-full"}`}
        style={{ width: 320, visibility: open ? "visible" : "hidden" }}
      >
        <div className="flex-1 overflow-y-auto sidebar-scroll">
          <div className="px-4 py-3 border-b border-slate-700/60">
            <div className="flex items-center justify-between gap-3">
              <div className="flex bg-slate-800 rounded-full p-0.5 gap-0.5">
                <button type="button" data-testid="lang-en" onClick={() => switchLang("en")} aria-label={t("language")} title={t("language")} className={`px-3 py-1 rounded-full text-xs font-bold ${lang === "en" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"}`}>EN</button>
                <button type="button" data-testid="lang-fr" onClick={() => switchLang("fr")} aria-label={t("language")} title={t("language")} className={`px-3 py-1 rounded-full text-xs font-bold ${lang === "fr" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"}`}>FR</button>
              </div>
              <Toggle labelLeft={t("dark")} labelRight={t("light")} active={isLightMode} onChange={onLightModeChange} />
            </div>
          </div>

          {/* ── L'expédition entière : la route en chiffres + les escales ── */}
          <div className="px-4 py-3 border-b border-slate-700/60">
            <SectionTitle>{t("expeditionTitle")}</SectionTitle>
            <ExpeditionBox
              routeDistanceNm={routeDistanceNm}
              routeSegmentCount={routeSegmentCount}
              routeCounts={routeCounts}
              waypointCount={points.length}
              escaleMarks={escaleMarks}
              segments={segments}
              filmNm={filmNm}
              nowMs={nowMs}
              liveFilmNm={liveFilmNm}
              officialEta={officialEta}
              onSeekEscale={onSeekEscale}
              onEscaleSheet={onEscaleSheet}
              drawing={drawing}
              frozen={frozen}
              ampNearby={ampNearby}
            />
            {showDeparture ? (
              <div className="mt-2">
                <DepartureField t0={departureT0} onT0={onDepartureT0} />
              </div>
            ) : null}
          </div>

          <div className="px-4 py-3 border-b border-slate-700/60" data-testid="export-box">
            <SectionTitle>{t("exportTitle")}</SectionTitle>
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="export-geojson"
                disabled={!canExport}
                title={geoTitle}
                onClick={handleExportGeoJSON}
                className={`flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold border ${
                  canExport
                    ? "border-sky-500/40 bg-sky-900/30 text-sky-100 hover:bg-sky-800/40"
                    : "border-slate-700 bg-slate-800/40 text-slate-500 cursor-not-allowed"
                }`}
              >
                {t("exportGeoJSON")}
              </button>
              <button
                type="button"
                data-testid="export-kml"
                disabled={!canExport}
                title={kmlTitle}
                onClick={handleExportKML}
                className={`flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold border ${
                  canExport
                    ? (exportMode === "suivre"
                      ? "border-teal-400 bg-teal-700 text-white hover:bg-teal-800"
                      : "border-teal-500/40 bg-teal-900/30 text-teal-100 hover:bg-teal-800/40")
                    : "border-slate-700 bg-slate-800/40 text-slate-500 cursor-not-allowed"
                }`}
              >
                {t("exportKML")}
              </button>
            </div>
          </div>

          {/* ── Réglages : polaire compacte, clé admin, paramètres avancés, calques ── */}
          <div className="px-4 py-3 space-y-2">
            {tracerLayout ? (
              <FoldDetails
                className="rounded-xl border border-slate-700/40 bg-slate-800/40 group"
                testId="polar-box"
                storageKey={POLAR_FOLD_KEY}
                fallbackOpen={false}
              >
                <summary className="cursor-pointer select-none list-none px-3 py-2 flex items-center gap-2">
                  <span className={`flex items-center gap-2 text-xs min-w-0 ${polarStatus.color}`}>
                    {polarStatus.icon}
                    <span className="font-medium min-w-0 truncate" data-testid="polar-status">{polarStatus.text}</span>
                  </span>
                  <span className="ml-auto text-slate-500 group-open:rotate-90 transition-transform">›</span>
                </summary>
                <div className="px-3 pb-2">
                  {(polarData?.boat_name || polarData?.name) ? (
                    <div className="mt-1 text-[11px] text-slate-200 truncate" data-testid="polar-boat">
                      {polarData.boat_name || polarData.name}
                    </div>
                  ) : null}
                  <div
                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault(); setIsDragging(false);
                      const f = e.dataTransfer.files?.[0];
                      const ok = [".pdf", ".csv", ".xlsx", ".xls"];
                      if (f && ok.some((ext) => f.name.toLowerCase().endsWith(ext))) {
                        userDroppedFileRef.current = true;
                        setPolarFile(f);
                      }
                    }}
                    onClick={() => polarFileInputRef.current?.click()}
                    data-testid="polar-drop"
                    className={`mt-1.5 flex items-center justify-center gap-1.5 px-2 py-1 border border-dashed rounded-lg cursor-pointer text-[10px]
                      ${isDragging ? "border-blue-400 bg-blue-900/20 text-blue-200" : "border-slate-600 hover:border-slate-500 text-slate-400"}`}
                  >
                    <input
                      ref={polarFileInputRef}
                      name="polar-file"
                      type="file"
                      accept=".pdf,.csv,.xlsx,.xls"
                      className="hidden"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) { userDroppedFileRef.current = true; setPolarFile(f); } }}
                    />
                    <Upload size={11} />
                    <span>{polarData ? t("polarDropToReplace") : t("polarDropZone")}</span>
                  </div>
                  {(polarData?.raw?.twa_rows || polarData?.vmg_summary) ? (
                    <button
                      type="button"
                      onClick={() => setShowPolar((v) => !v)}
                      aria-expanded={showPolar}
                      data-testid="polar-show"
                      className="mt-1.5 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10"
                    >
                      {showPolar ? t("polarHide") : t("polarShow")}
                    </button>
                  ) : null}
                  {showPolar && polarData?.raw?.twa_rows ? (
                    <PolarSpeedGrid raw={polarData.raw} lang={lang} />
                  ) : null}
                  {showPolar && !polarData?.raw?.twa_rows && polarData?.vmg_summary && (
                    <div className="mt-2 overflow-x-auto rounded-lg border border-slate-700/40 bg-slate-900/40" data-testid="polar-table">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-slate-800/80 border-b border-slate-700/60">
                            <th rowSpan={2} className="py-1.5 px-1.5 text-center text-blue-300 font-bold">TWS</th>
                            <th colSpan={3} className="py-1 text-center text-green-400">{t("polarUpwind")}</th>
                            <th colSpan={3} className="py-1 text-center text-amber-400">{t("polarDownwind")}</th>
                          </tr>
                          <tr className="bg-slate-800/60 border-b border-slate-700/60">
                            {["TWA", "BS", "VMG", "TWA", "BS", "VMG"].map((h, i) => (
                              <th key={i} className="py-1 px-1 font-medium text-slate-400">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {POLAR_VMG_TWS_KEYS.map((tws) => (
                            <PolarVmgRow key={tws} tws={tws} entry={polarData.vmg_summary[tws]} />
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </FoldDetails>
            ) : (
            <div className="rounded-xl border border-slate-700/40 bg-slate-800/40 px-3 py-2" data-testid="polar-box">
              <div className={`flex items-center gap-2 text-xs ${polarStatus.color}`}>
                {polarStatus.icon}
                <span className="font-medium min-w-0 truncate" data-testid="polar-status">{polarStatus.text}</span>
                {(polarData?.raw?.twa_rows || polarData?.vmg_summary) ? (
                  <button
                    type="button"
                    onClick={() => setShowPolar((v) => !v)}
                    aria-expanded={showPolar}
                    data-testid="polar-show"
                    className="ml-auto flex-shrink-0 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10"
                  >
                    {showPolar ? t("polarHide") : t("polarShow")}
                  </button>
                ) : null}
              </div>
              {(polarData?.boat_name || polarData?.name) ? (
                <div className="mt-1 text-[11px] text-slate-200 truncate" data-testid="polar-boat">
                  {polarData.boat_name || polarData.name}
                </div>
              ) : null}
              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault(); setIsDragging(false);
                  const f = e.dataTransfer.files?.[0];
                  const ok = [".pdf", ".csv", ".xlsx", ".xls"];
                  if (f && ok.some((ext) => f.name.toLowerCase().endsWith(ext))) {
                    userDroppedFileRef.current = true;
                    setPolarFile(f);
                  }
                }}
                onClick={() => polarFileInputRef.current?.click()}
                data-testid="polar-drop"
                className={`mt-1.5 flex items-center justify-center gap-1.5 px-2 py-1 border border-dashed rounded-lg cursor-pointer text-[10px]
                  ${isDragging ? "border-blue-400 bg-blue-900/20 text-blue-200" : "border-slate-600 hover:border-slate-500 text-slate-400"}`}
              >
                <input
                  ref={polarFileInputRef}
                  name="polar-file"
                  type="file"
                  accept=".pdf,.csv,.xlsx,.xls"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) { userDroppedFileRef.current = true; setPolarFile(f); } }}
                />
                <Upload size={11} />
                <span>{polarData ? t("polarDropToReplace") : t("polarDropZone")}</span>
              </div>
              {showPolar && polarData?.raw?.twa_rows ? (
                <PolarSpeedGrid raw={polarData.raw} lang={lang} />
              ) : null}
              {showPolar && !polarData?.raw?.twa_rows && polarData?.vmg_summary && (
                <div className="mt-2 overflow-x-auto rounded-lg border border-slate-700/40 bg-slate-900/40" data-testid="polar-table">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-slate-800/80 border-b border-slate-700/60">
                        <th rowSpan={2} className="py-1.5 px-1.5 text-center text-blue-300 font-bold">TWS</th>
                        <th colSpan={3} className="py-1 text-center text-green-400">{t("polarUpwind")}</th>
                        <th colSpan={3} className="py-1 text-center text-amber-400">{t("polarDownwind")}</th>
                      </tr>
                      <tr className="bg-slate-800/60 border-b border-slate-700/60">
                        {["TWA", "BS", "VMG", "TWA", "BS", "VMG"].map((h, i) => (
                          <th key={i} className="py-1 px-1 font-medium text-slate-400">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {POLAR_VMG_TWS_KEYS.map((tws) => (
                        <PolarVmgRow key={tws} tws={tws} entry={polarData.vmg_summary[tws]} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            )}

            <TavilyWatchToggle />
            <AdminKeyField />
          </div>

          {skipperOrders && (
            <SkipperOrdersPanel
              orders={skipperOrders}
              profile={skipperProfile}
              onProfile={onSkipperProfile}
              onComfort={onSkipperComfort}
              onHorizon={onSkipperHorizon}
              onExpert={onSkipperExpert}
              onBoat={onSkipperBoat}
              onReset={onSkipperReset}
              suggest={skipperSuggest}
              onAcceptSuggest={onSkipperSuggestAccept}
              onDismissSuggest={onSkipperSuggestDismiss}
            />
          )}

          {maritimeLayers ? (
            <LayersDrawer
              key={tracerLayout ? "layers-tracer" : "layers-follow"}
              tracerLayout={tracerLayout}
              layersOn={layersOn}
              t={t}
              maritimeLayers={maritimeLayers}
            />
          ) : null}
        </div>
      </div>
    </>
  );
});

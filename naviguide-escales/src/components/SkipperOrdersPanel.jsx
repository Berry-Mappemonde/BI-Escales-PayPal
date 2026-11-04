import { memo, useEffect, useState } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import {
  BOAT_FIELDS,
  COMFORTS,
  COMFORT_DEFAULT,
  DEFAULT_PROFILE,
  EXPERT_FIELDS,
  EXPERT_IDS,
  HORIZONS_H,
  PROFILES,
  resolveOrders,
} from "../engine/skipperOrders.js";

const PROFILE_KEY = {
  coastal: "skipperProfileCoastal",
  cruise: "skipperProfileCruise",
  ocean: "skipperProfileOcean",
};

const COMFORT_KEY = {
  soft: "skipperComfortSoft",
  normal: "skipperComfortNormal",
  hard: "skipperComfortHard",
};

/** i18n label per Expert id (S7). Units come from the resolved thresholds. */
const EXPERT_KEY = {
  galeKt: "skipperExpertGaleKt",
  galeHoldKt: "skipperExpertGaleHoldKt",
  galePct: "skipperExpertGalePct",
  windShiftResetKt: "skipperExpertWindResetKt",
  windShiftResetDeg: "skipperExpertWindResetDeg",
  currentIgnoreKn: "skipperExpertCurrentIgnore",
  currentInvertDeg: "skipperExpertCurrentInvert",
  rainMmH: "skipperExpertRainMmH",
  rain3hMm: "skipperExpertRain3h",
  marinaRefugeNm: "skipperExpertMarinaNm",
  marinaRefugeCooldownMin: "skipperExpertMarinaCooldown",
  iciRadiusNm: "skipperExpertIciRadius",
  alongAmpNm: "skipperExpertAlongAmp",
  ampAheadMinNm: "skipperExpertAmpAhead",
};

/** The gale pair lives in the boat block (top), the rest under « Chiffres ». */
const BOAT_EXPERT_IDS = ["galeKt", "galeHoldKt"];
const NUMBER_EXPERT_IDS = EXPERT_IDS.filter((id) => !BOAT_EXPERT_IDS.includes(id));

function num(n, lang, digits = null) {
  if (!Number.isFinite(n)) return "—";
  const s = digits == null ? String(n) : n.toFixed(digits);
  return lang === "en" ? s : s.replace(".", ",");
}

function Row({ label, value, muted = false }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-slate-700/40 last:border-0">
      <span className="text-[11px] text-slate-400">{label}</span>
      <span className={`text-[11px] font-semibold text-right ${muted ? "text-slate-400" : "text-white"}`}>{value}</span>
    </div>
  );
}

/**
 * Remise d’un chiffre : valeur du profil courant (bateau = polar / défaut
 * Berry), `forced` faux. Le bouton appelle `onChange(id, null)` — setExpert /
 * setBoat effacent le forçage et `resolveOrders` renvoie ce résultat.
 */
export function resetNumberToProfile(id, profile = DEFAULT_PROFILE) {
  const orders = resolveOrders({ profile });
  const value = id in BOAT_FIELDS ? orders.boat[id] : orders.values[id];
  return { value, forced: false };
}

/**
 * One editable number: input + unit + « back to default » arrow.
 * Draft while typing: clamp-on-keystroke (setExpert → clampExpert) turned
 * « 34 → 2 → 29 » into 20 then 50, so ↺ never saw 29 (:5174).
 */
function NumberRow({ id, label, value, unit, field, forced, onChange, onReset, resetTitle, testPrefix = "skipper-expert", hint = "" }) {
  const [draft, setDraft] = useState(null);
  useEffect(() => { setDraft(null); }, [value]);
  const shown = draft != null ? draft : (value ?? "");
  const draftNum = draft != null && draft !== "" ? Number(draft) : NaN;
  const dirty = draft != null && !(Number.isFinite(draftNum) && draftNum === Number(value));
  const canReset = Boolean(forced) || dirty;
  const handleReset = () => {
    setDraft(null);
    if (onReset) onReset(id);
    else onChange?.(id, null);
  };
  const commit = (raw) => {
    setDraft(null);
    onChange?.(id, raw);
  };
  return (
    <div className="flex items-center justify-between gap-2 py-1 border-b border-slate-700/40 last:border-0">
      <label htmlFor={`${testPrefix}-${id}`} className={`text-[11px] ${canReset ? "text-amber-200" : "text-slate-400"}`}>
        {label}
        {hint ? <span className="ml-1 text-[9px] text-slate-500">{hint}</span> : null}
      </label>
      <span className="flex items-center gap-1">
        <input
          id={`${testPrefix}-${id}`}
          type="number"
          inputMode="decimal"
          min={field.min}
          max={field.max}
          step={field.step}
          value={shown}
          onChange={(e) => {
            const raw = e.target.value;
            const n = Number(raw);
            if (raw !== "" && Number.isFinite(n) && n >= field.min && n <= field.max) {
              commit(raw);
              return;
            }
            setDraft(raw);
          }}
          onBlur={(e) => {
            if (draft == null) return;
            commit(e.target.value);
          }}
          data-testid={`${testPrefix}-${id}`}
          className={`w-16 bg-slate-900 border rounded px-1 py-0.5 text-[11px] text-right text-white ${
            canReset ? "border-amber-500/60" : "border-slate-700"
          }`}
        />
        <span className="text-[10px] text-slate-500 w-10">{unit}</span>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={handleReset}
          disabled={!canReset}
          data-testid={`${testPrefix}-${id}-reset`}
          aria-label={resetTitle}
          title={resetTitle}
          className={`text-[11px] px-1 rounded ${canReset ? "text-amber-200 hover:bg-white/10" : "text-slate-700 cursor-default"}`}
        >
          ↺
        </button>
      </span>
    </div>
  );
}

/** Small pill group shared by character (v1), comfort and horizon (S6). */
function Pills({ items, value, onPick, label, disabled = false, testPrefix, render }) {
  return (
    <div
      role="group"
      aria-label={label}
      className={`flex bg-slate-800 rounded-full p-0.5 gap-0.5 ${disabled ? "opacity-50" : ""}`}
    >
      {items.map((it) => (
        <button
          key={String(it)}
          type="button"
          disabled={disabled}
          onClick={() => onPick?.(it)}
          aria-pressed={value === it}
          data-testid={`${testPrefix}-${it}`}
          className={`flex-1 px-2 py-1 rounded-full text-xs font-bold transition-colors ${
            value === it ? "bg-sky-600 text-white" : "text-slate-400 hover:text-white"
          } ${disabled ? "cursor-not-allowed hover:text-slate-400" : ""}`}
        >
          {render(it)}
        </button>
      ))}
    </div>
  );
}

/**
 * « Paramètres avancés » — folded by default (revue du 19 sept.). Inside, top
 * to bottom: the boat (length / draft typed by the skipper, planning speed,
 * gale — the polar name lives under Polaires, once), then the character /
 * comfort / horizon pills, then the « Chiffres » Expert drawer. Cinema hides
 * the sidebar: the orders stay active.
 */
export const SkipperOrdersPanel = memo(function SkipperOrdersPanel({
  orders,
  profile,
  onProfile,
  onComfort,
  onHorizon,
  onExpert,
  onBoat,
  onReset,
  suggest = null,
  onAcceptSuggest,
  onDismissSuggest,
}) {
  const { lang, t } = useLang();
  if (!orders) return null;
  const T = orders.values;
  const boat = orders.boat;
  const isSuivre = orders.mode === "suivre";
  const comfort = orders.comfort || COMFORT_DEFAULT;
  const comfortPhrase = orders.comfortPhrase ? (lang === "en" ? orders.comfortPhrase.en : orders.comfortPhrase.fr) : "";
  const horizonH = orders.knobs?.horizonH ?? T.suivreLookaheadH;
  const expert = orders.expert || {};
  const expertCount = Object.keys(expert).length;
  const boatTouched = boat.source.loa === "skipper" || boat.source.draft === "skipper";
  const unitOf = (id) => orders.thresholds.find((x) => x.id === id)?.unit || "";
  const touched = profile !== "cruise"
    || comfort !== COMFORT_DEFAULT
    || horizonH !== orders.knobs?.horizonDefaultH
    || expertCount > 0
    || boatTouched;
  return (
    <details className="px-4 py-3 border-t border-slate-700/60 group" data-testid="skipper-orders">
      <summary className="cursor-pointer select-none list-none flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-slate-200">{t("advancedSettings")}</span>
        <span className="text-slate-500 group-open:rotate-90 transition-transform">›</span>
      </summary>

      {/* Le bateau : longueur / tirant d’eau saisis, vitesse de planning, coup de vent. */}
      <div className="mt-2 bg-slate-800/60 rounded-xl px-3 py-0.5 border border-slate-700/40" data-testid="skipper-boat">
        <NumberRow
          id="loaM"
          label={t("skipperLoa")}
          value={boat.loaM}
          unit="m"
          field={BOAT_FIELDS.loaM}
          forced={boat.source.loa === "skipper"}
          onChange={onBoat}
          onReset={(fieldId) => onBoat?.(fieldId, null)}
          resetTitle={t("skipperBoatReset")}
          testPrefix="skipper-boat"
          hint={boat.source.loa === "polar" ? t("skipperFromPolar") : (boat.source.loa === "default" ? t("skipperBerryDefault") : "")}
        />
        <NumberRow
          id="draftM"
          label={t("skipperDraft")}
          value={boat.draftM}
          unit="m"
          field={BOAT_FIELDS.draftM}
          forced={boat.source.draft === "skipper"}
          onChange={onBoat}
          onReset={(fieldId) => onBoat?.(fieldId, null)}
          resetTitle={t("skipperBoatReset")}
          testPrefix="skipper-boat"
          hint={boat.source.draft === "polar" ? t("skipperFromPolar") : (boat.source.draft === "default" ? t("skipperBerryDefault") : "")}
        />
        <Row
          label={t("skipperPlanningKn")}
          value={`${num(T.planningKn, lang)} kn · ${
            boat.source.planningKn === "grib"
              ? t("skipperPlanningGrib", { tws: num(boat.planningWind?.tws, lang), twa: boat.planningWind?.twa })
              : boat.source.planningKn === "climatology"
                ? t("skipperPlanningClimo", { tws: num(boat.planningWind?.tws, lang), twa: boat.planningWind?.twa })
                : boat.source.planningKn === "polar" ? t("skipperFromPolar") : t("skipperProfileDefault")
          }`}
        />
        {BOAT_EXPERT_IDS.map((id) => (
          <NumberRow
            key={id}
            id={id}
            label={t(EXPERT_KEY[id])}
            value={T[id]}
            unit={unitOf(id)}
            field={EXPERT_FIELDS[id]}
            forced={id in expert}
            onChange={onExpert}
            onReset={(fieldId) => onExpert?.(fieldId, null)}
            resetTitle={t("skipperExpertReset")}
            hint={id in expert ? "" : (id === "galeKt" ? "Beaufort 8" : "Beaufort 7")}
          />
        ))}
        {isSuivre && (
          <Row
            label={t("skipperSuivreWindow")}
            value={`${orders.budget.hours} h · ${num(orders.budget.maxNm, lang)} nm`}
          />
        )}
      </div>

      {/* Caractère, confort, anticipation — sur trois lignes compactes. */}
      <div className="mt-2 space-y-2">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">{t("skipperProfileTitle")}</div>
          <Pills
            items={PROFILES}
            value={profile}
            onPick={onProfile}
            label={t("skipperProfileAria")}
            testPrefix="skipper-profile"
            render={(p) => t(PROFILE_KEY[p])}
          />
          <p className="mt-1 text-[10px] text-sky-200 italic leading-snug" data-testid="skipper-phrase">
            {lang === "en" ? orders.phrase.en : orders.phrase.fr}
          </p>
          <p className="text-[10px] text-slate-300 leading-snug" data-testid="skipper-orders-line">
            {lang === "en"
              ? `Hs ${num(T.hsAlertM, lang, 1)} m · depth ${T.depthAlertM} m`
              : `Hs ${num(T.hsAlertM, lang, 1)} m · fond ${T.depthAlertM} m`}
          </p>
          <p className="text-[10px] text-slate-400 leading-snug" data-testid="skipper-coastal-rule">
            {t("skipperCoastalRule")}
          </p>
        </div>
        <div data-testid="skipper-comfort">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase tracking-wide text-slate-500">{t("skipperComfortTitle")}</span>
            <span className="text-[10px] text-slate-400" data-testid="skipper-comfort-effect">
              {`+${num(T.windShiftKt, lang)} kn / ${num(T.windShiftDeg, lang)}° · Hs ${num(T.hsAlertM, lang, 1)} m`}
            </span>
          </div>
          <Pills
            items={COMFORTS}
            value={comfort}
            onPick={onComfort}
            label={t("skipperComfortAria")}
            testPrefix="skipper-comfort"
            render={(c) => t(COMFORT_KEY[c])}
          />
          {comfortPhrase && (
            <p className="mt-1 text-[10px] text-sky-200 italic leading-snug" data-testid="skipper-comfort-phrase">{comfortPhrase}</p>
          )}
        </div>
        <div data-testid="skipper-horizon">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase tracking-wide text-slate-500">{t("skipperSuivreWindow")}</span>
            <span className="text-[10px] text-slate-400">
              {isSuivre
                ? `${num(orders.budget.maxNm, lang)} nm · ${orders.budget.maxPearls} ${t("skipperPearls")}`
                : t("skipperHorizonLeg")}
            </span>
          </div>
          <Pills
            items={HORIZONS_H}
            value={horizonH}
            onPick={onHorizon}
            label={t("skipperHorizonAria")}
            disabled={!isSuivre}
            testPrefix="skipper-horizon"
            render={(h) => `${h} h`}
          />
        </div>
      </div>

      {/* S7 — « Chiffres », repliés eux aussi. */}
      <details className="mt-2 group/expert" data-testid="skipper-expert">
        <summary className="cursor-pointer select-none text-[10px] uppercase tracking-wide text-slate-500 hover:text-slate-300 list-none flex items-center justify-between">
          <span>{t("skipperExpertTitle")}{expertCount ? ` · ${expertCount}` : ""}</span>
          <span className="text-slate-600 group-open/expert:rotate-90 transition-transform">›</span>
        </summary>
        <div className="mt-1 bg-slate-800/60 rounded-xl px-3 py-0.5 border border-slate-700/40">
          {NUMBER_EXPERT_IDS.map((id) => (
            <NumberRow
              key={id}
              id={id}
              label={t(EXPERT_KEY[id])}
              value={T[id]}
              unit={unitOf(id)}
              field={EXPERT_FIELDS[id]}
              forced={id in expert}
              onChange={onExpert}
              onReset={(fieldId) => onExpert?.(fieldId, null)}
              resetTitle={t("skipperExpertReset")}
            />
          ))}
        </div>
      </details>

      {suggest && (
        <div className="mt-2 text-[10px] rounded-md px-2 py-1 border border-amber-500/30 text-amber-200 leading-snug" data-testid="skipper-suggest">
          <span>{t("skipperSuggestCoastal", { loa: num(boat.loaM, lang), draft: num(boat.draftM, lang, 1) })}</span>
          <span className="ml-2 inline-flex gap-1">
            <button type="button" onClick={onAcceptSuggest} className="px-1.5 rounded bg-amber-500/20 hover:bg-amber-500/40 text-amber-100">{t("skipperSuggestYes")}</button>
            <button type="button" onClick={onDismissSuggest} className="px-1.5 rounded hover:bg-white/10 text-amber-200/80">{t("skipperSuggestNo")}</button>
          </span>
        </div>
      )}

      {touched && (
        <button
          type="button"
          onClick={onReset}
          data-testid="skipper-reset"
          className="mt-2 text-[10px] text-slate-500 underline underline-offset-2 hover:text-slate-300"
        >
          {t("skipperResetBerry")}
        </button>
      )}
    </details>
  );
});

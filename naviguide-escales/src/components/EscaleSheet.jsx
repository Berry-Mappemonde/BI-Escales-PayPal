import { memo } from "react";
import { X } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { googleMapsUrl } from "../engine/briefingLinks.js";
import { localizePlaceName } from "../utils/placeNames.js";
import { displayStopName } from "../utils/stopLabels.js";
import { LlmSourceBadge } from "./LlmSourceBadge.jsx";

/** Section / subsection labels; anything unknown falls back to the raw key. */
const LABELS = {
  fr: {
    mooring: "Amarrage", marinas: "Marinas", capitaineries: "Capitainerie", wpi: "Ports WPI", anchorages: "Mouillages",
    services: "Services", fuel: "Carburant", water: "Eau", electricity: "Électricité",
    supplies: "Avitaillement", supermarkets: "Commerces", laundry: "Laverie",
    maintenance: "Entretien", chandlery: "Accastillage", boatyards: "Chantiers", cranes: "Grues", slipways: "Cales",
    tourism: "Tourisme", sights: "Sites", museums: "Musées", viewpoints: "Points de vue", information: "Office de tourisme",
    health: "Santé", pharmacies: "Pharmacies", hospitals: "Hôpitaux",
    formalities: "Formalités", zee: "ZEE", poe: "Ports d’entrée officiels", amp: "Aires marines protégées",
    around: "Autour", projects: "Projets", science: "Fiches science",
  },
  en: {
    mooring: "Mooring", marinas: "Marinas", capitaineries: "Harbour master", wpi: "WPI ports", anchorages: "Anchorages",
    services: "Services", fuel: "Fuel", water: "Water", electricity: "Electricity",
    supplies: "Supplies", supermarkets: "Shops", laundry: "Laundry",
    maintenance: "Maintenance", chandlery: "Chandlery", boatyards: "Boatyards", cranes: "Cranes", slipways: "Slipways",
    tourism: "Tourism", sights: "Sights", museums: "Museums", viewpoints: "Viewpoints", information: "Tourist office",
    health: "Health", pharmacies: "Pharmacies", hospitals: "Hospitals",
    formalities: "Formalities", zee: "EEZ", poe: "Official ports of entry", amp: "Marine protected areas",
    around: "Around", projects: "Projects", science: "Science sheets",
  },
};

/** Subsection → entity kind understood by the briefing focus (layer on + pin). */
const SUB_KIND = {
  marinas: "marina", capitaineries: "capitainerie", wpi: "wpi", anchorages: "anchorage",
  poe: "poe", amp: "amp", projects: "project", science: "science",
};

function label(key, lang) {
  return (LABELS[lang === "en" ? "en" : "fr"][key]) || key;
}

function nm(v, lang) {
  if (!Number.isFinite(v)) return "";
  return `${Number(v).toLocaleString(lang === "en" ? "en-GB" : "fr-FR", { maximumFractionDigits: 1 })} nm`;
}

const Item = memo(function Item({ item, sub, lang, onFocus, t }) {
  const gm = googleMapsUrl(item.lat, item.lon);
  const site = item.url || item.visit_url || item.manager_url || null;
  return (
    <li className="flex flex-wrap items-baseline gap-1 min-w-0 text-[11px] leading-snug">
      {onFocus && Number.isFinite(item.lat) && Number.isFinite(item.lon) ? (
        <button
          type="button"
          className="text-left text-slate-100 hover:text-cyan-200 underline decoration-dotted underline-offset-2 truncate"
          title={t("momentSeeOnMap")}
          onClick={() => onFocus({ name: item.name, lat: item.lat, lon: item.lon, kind: SUB_KIND[sub] || "place", source: item.source, url: site })}
        >
          {item.name}
        </button>
      ) : (
        <span className="text-slate-100 truncate">{item.name}</span>
      )}
      {Number.isFinite(item.nm) ? <span className="text-slate-500 text-[9px] shrink-0">{nm(item.nm, lang)}</span> : null}
      {item.fuel?.length ? <span className="text-slate-500 text-[9px] shrink-0">{item.fuel.join(" · ")}</span> : null}
      {item.phone ? <a href={`tel:${item.phone}`} className="text-slate-400 text-[9px] shrink-0 hover:text-cyan-200">{item.phone}</a> : null}
      {site ? <a href={site} target="_blank" rel="noopener noreferrer" className="text-cyan-300/80 text-[10px] shrink-0 hover:text-cyan-200" title={site}>↗</a> : null}
      {gm ? <a href={gm} target="_blank" rel="noopener noreferrer" className="text-cyan-300/80 text-[10px] shrink-0 hover:text-cyan-200" title="Google Maps">◎</a> : null}
      {item.enrich?.text || item.phrase ? (
        <span data-testid="escale-enrich" className="text-slate-400 text-[10px] min-w-0 basis-full">
          {item.enrich?.text || item.phrase}
          {item.enrich?.url ? (
            <a href={item.enrich.url} target="_blank" rel="noopener noreferrer" className="ml-1 text-cyan-300/80 hover:text-cyan-200">↗</a>
          ) : null}
        </span>
      ) : null}
    </li>
  );
});

function ZeeLine({ zee, lang }) {
  if (!zee?.name) return null;
  const gold = zee.gold ? (lang === "en" ? " · Gold formalities" : " · formalités Gold") : "";
  const name = localizePlaceName(zee.name, lang);
  return <li className="text-[11px] text-slate-200 leading-snug">{name}{gold}</li>;
}

/**
 * The sheet of a stop: a paragraph (usual LLM cascade, from the lists
 * only) then the lists themselves — every line a place with map focus, site
 * and Google Maps. Empty sections are simply not there.
 */
export const EscaleSheet = memo(function EscaleSheet({ stop, fiche, loading, error, onClose, onFocus }) {
  const { t, lang } = useLang();
  if (!stop) return null;
  const sections = fiche?.sections || {};
  const keys = Object.keys(sections);
  const paragraph = fiche?.paragraph?.status === "ready" ? fiche.paragraph.text : "";

  return (
    <div data-testid="escale-sheet" className="rounded-lg border border-emerald-500/30 bg-emerald-950/30 p-2 min-w-0">
      <div className="flex items-center gap-1.5 mb-1">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-200 leading-snug">{t("escaleSheetTitle")}</div>
          <div className="text-[12px] font-semibold text-white leading-snug truncate">{displayStopName(stop.name, lang, t)}</div>
        </div>
        {onClose ? (
          <button
            type="button"
            data-testid="escale-close"
            onMouseDown={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onClose();
            }}
            className="w-6 h-6 flex items-center justify-center shrink-0 rounded-md text-slate-400 hover:text-white hover:bg-white/10"
            title={t("momentClose")}
            aria-label={t("momentClose")}
          >
            <X size={13} />
          </button>
        ) : null}
      </div>

      {loading ? <p className="text-[11px] text-slate-400 leading-snug">{t("escaleSheetLoading")}</p> : null}
      {error ? <p className="text-[11px] text-amber-300/90 leading-snug">{t("escaleSheetError")}</p> : null}

      {paragraph ? (
        <p className="text-[11px] text-slate-100 leading-snug mb-1.5 break-words [overflow-wrap:anywhere]">{paragraph}</p>
      ) : null}
      {paragraph && (fiche?.paragraph?.source || fiche?.paragraph?.engine) ? (
        <LlmSourceBadge
          source={fiche.paragraph.source || fiche.paragraph.engine}
          testId="escale-source"
          className="-mt-1 mb-1.5"
        />
      ) : null}

      {!loading && fiche && !keys.length ? (
        <p className="text-[11px] text-slate-400 leading-snug">{t("escaleSheetEmpty")}</p>
      ) : null}

      {keys.map((section) => (
        <div key={section} className="mt-1.5 first:mt-0">
          <div className="text-[10px] font-semibold text-emerald-200/90 leading-snug">{label(section, lang)}</div>
          {Object.entries(sections[section]).map(([sub, items]) => (
            <div key={sub} className="pl-1.5 mt-0.5">
              {Array.isArray(items) ? (
                <>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 leading-snug">{label(sub, lang)}</div>
                  <ul className="space-y-0.5 min-w-0">
                    {items.map((item, i) => (
                      <Item key={`${item.name}-${i}`} item={item} sub={sub} lang={lang} onFocus={onFocus} t={t} />
                    ))}
                  </ul>
                </>
              ) : sub === "zee" ? (
                <ul><ZeeLine zee={items} lang={lang} /></ul>
              ) : null}
            </div>
          ))}
        </div>
      ))}

      {fiche?.sources ? (
        <div className="text-[9px] text-slate-500 leading-snug mt-1.5">
          {t("escaleSheetSources")} : OpenStreetMap{fiche.sources.bi ? " · Blue Intelligence" : ""}{fiche.paragraph?.engine ? ` · ${fiche.paragraph.engine}` : ""}
        </div>
      ) : null}
    </div>
  );
});

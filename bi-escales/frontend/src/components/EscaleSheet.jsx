/**
 * Fiche d'escale. Dérivée de naviguide-escales/src/components/EscaleSheet.jsx.
 * Le paragraphe narratif, le badge LLM et la section formalités (PoE) sont retirés.
 * Le bouton PayPal (PledgeButton, PR #2) est hébergé ici.
 * googleMapsUrl est la fonction du même nom dans engine/briefingLinks.js.
 */
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { HELLOASSO_MEMBERSHIP_URL } from "../config/helloasso.js";
import { PledgeButton } from "./PledgeButton";
import { formatStopoverDate, portHoldHours } from "../voyage/voyageClock.js";
import { formatLogbookEntry } from "../voyage/journalDisplay.js";
import { evaluateGooglePlaceLink, googleMapsSearchUrl } from "../marinas/marinaPlaceLink.js";

const STOP_KINDS = ["mile", "night", "meal", "care", "common_fund"];
const FIXED_AMOUNT = { night: "60.00", meal: "60.00", care: "40.00" };

const SECTION_KEYS = [
  "mooring",
  "marinas",
  "capitaineries",
  "wpi",
  "anchorages",
  "services",
  "fuel",
  "water",
  "around",
  "projects",
];

function marinaMapsUrl(item) {
  const ev = evaluateGooglePlaceLink(item);
  return ev.mapsLink || googleMapsSearchUrl(item.lat, item.lon);
}

function marinaFactLines(item, t) {
  const lines = [];
  if (item.canal_vhf) {
    lines.push(`${t("sheet.marina.vhf")}: ${item.canal_vhf}`);
  }
  if (item.places_visiteurs != null && item.places_visiteurs !== "") {
    lines.push(`${t("sheet.marina.visitorBerths")}: ${item.places_visiteurs}`);
  }
  if (item.tirant_eau_max_metres != null && item.tirant_eau_max_metres !== "") {
    lines.push(`${t("sheet.marina.maxDraft")}: ${item.tirant_eau_max_metres} m`);
  }
  if (item.score_protection_meteo != null && item.score_protection_meteo !== "") {
    lines.push(`${t("sheet.marina.weatherShelter")}: ${item.score_protection_meteo}/5`);
  }
  if (Array.isArray(item.services) && item.services.length) {
    lines.push(`${t("sheet.marina.services")}: ${item.services.join(", ")}`);
  }
  if (item.resume_avis) {
    lines.push(`${t("sheet.marina.review")}: ${item.resume_avis}`);
  }
  return lines;
}

export function visibleSections(sections) {
  const out = {};
  Object.entries(sections || {}).forEach(([key, value]) => {
    if (key === "formalities") return;
    out[key] = value;
  });
  return out;
}

function sectionLabel(key, t) {
  const path = `sheet.sections.${key}`;
  const text = t(path);
  return text === path ? key : text;
}

export const EscaleSheet = memo(function EscaleSheet({
  stop,
  fiche,
  loading,
  error,
  onClose,
  pledge,
  onPledgeAuthorized,
  arrivalIso,
  logbookEntries,
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  if (!stop) return null;
  const sections = visibleSections(fiche?.sections);
  const keys = Object.keys(sections);
  const pledgeDescription = pledge
    ? `${stop.name} — ${t(`pledge.kinds.${pledge.kind}`)}`
    : "";
  const holdHours = portHoldHours(stop.name);
  const arrivalLabel = arrivalIso
    ? formatStopoverDate(arrivalIso, holdHours, lang)
    : "";
  const logLines = (logbookEntries || []).map((entry) => formatLogbookEntry(entry, lang));

  return (
    <div data-testid="escale-sheet" className="escale-sheet">
      <div className="escale-sheet-head">
        <div>
          <div className="escale-kicker">{t("sheet.title")}</div>
          <strong>{stop.name}</strong>
          {arrivalLabel ? (
            <p className="hint escale-eta" data-testid="escale-estimated-arrival">
              {t("sheet.estimatedArrival")}: {arrivalLabel}
            </p>
          ) : null}
        </div>
        {onClose ? (
          <button type="button" data-testid="escale-close" onClick={onClose} aria-label={t("sheet.close")}>
            ×
          </button>
        ) : null}
      </div>
      {loading ? <p className="hint">{t("sheet.loading")}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
      {logLines.length ? (
        <div className="escale-logbook" data-testid="escale-logbook">
          <div className="escale-kicker">{t("sheet.logbookTitle")}</div>
          <ul className="escale-items">
            {logLines.map((line, index) => (
              <li key={`${line}-${index}`}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!loading && fiche && !keys.length ? <p className="hint">{t("sheet.empty")}</p> : null}
      {keys.map((section) => (
        <div key={section}>
          <div className="escale-kicker">{sectionLabel(section, t)}</div>
          {Object.entries(sections[section] || {}).map(([sub, items]) => (
            Array.isArray(items) ? (
              <div key={sub}>
                <div className="hint">{SECTION_KEYS.includes(sub) ? sectionLabel(sub, t) : sub}</div>
                <ul className="escale-items">
                  {items.map((item, index) => {
                    const site = item.url || item.visit_url || null;
                    const maps = marinaMapsUrl(item);
                    const facts = sub === "marinas" ? marinaFactLines(item, t) : [];
                    return (
                      <li key={`${item.name}-${index}`}>
                        <span>{item.name}</span>
                        {Number.isFinite(item.nm) ? <span className="hint"> {item.nm} nm</span> : null}
                        {item.phone ? <a href={`tel:${item.phone}`}>{item.phone}</a> : null}
                        {site ? (
                          <a href={site} target="_blank" rel="noopener noreferrer" aria-label={t("sheet.marina.website")}>
                            ↗
                          </a>
                        ) : null}
                        {maps ? (
                          <a href={maps} target="_blank" rel="noopener noreferrer" aria-label={t("sheet.marina.maps")}>
                            ◎
                          </a>
                        ) : null}
                        {facts.map((line) => (
                          <div key={line} className="hint marina-fact" data-testid="marina-fact">
                            {line}
                          </div>
                        ))}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null
          ))}
        </div>
      ))}
      <p className="fund-line">
        {t("fund.line")}{" "}
        <a href={HELLOASSO_MEMBERSHIP_URL} target="_blank" rel="noreferrer">{t("fund.helloasso")}</a>
      </p>
      {pledge ? (
        <div className="pledge-form">
          <label>
            {t("pledge.kind")}
            <select
              data-testid="pledge-kind"
              value={pledge.kind}
              onChange={(event) => pledge.onKind(event.target.value)}
            >
              {STOP_KINDS.map((kind) => (
                <option key={kind} value={kind}>{t(`pledge.kinds.${kind}`)}</option>
              ))}
            </select>
          </label>
          <label>
            {t("pledge.amount")}
            <input
              data-testid="pledge-amount"
              value={FIXED_AMOUNT[pledge.kind] || pledge.amount}
              readOnly={Boolean(FIXED_AMOUNT[pledge.kind])}
              onChange={(event) => {
                if (!FIXED_AMOUNT[pledge.kind]) pledge.onAmount(event.target.value);
              }}
            />
          </label>
          <label>
            {t("pledge.contributor")}
            <input value={pledge.contributor} onChange={(event) => pledge.onContributor(event.target.value)} />
          </label>
          <PledgeButton
            values={{
              amount_eur: FIXED_AMOUNT[pledge.kind] || pledge.amount,
              description: pledgeDescription,
              milestone_id: pledge.milestoneId,
              contributor: pledge.contributor.trim() || undefined,
              kind: pledge.kind,
              target_id: pledge.milestoneId,
            }}
            onAuthorized={onPledgeAuthorized}
          />
        </div>
      ) : null}
    </div>
  );
});

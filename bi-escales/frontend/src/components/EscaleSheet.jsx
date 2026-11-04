/**
 * Fiche d'escale. Dérivée de naviguide-escales/src/components/EscaleSheet.jsx.
 * Le paragraphe narratif, le badge LLM et la section formalités (PoE) sont retirés.
 * Le bouton PayPal (PledgeButton, PR #2) est hébergé ici.
 * googleMapsUrl est la fonction du même nom dans engine/briefingLinks.js.
 */
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { PledgeButton } from "./PledgeButton";

const LABELS = {
  fr: {
    mooring: "Amarrage", marinas: "Marinas", capitaineries: "Capitainerie", wpi: "Ports WPI", anchorages: "Mouillages",
    services: "Services", fuel: "Carburant", water: "Eau",
    around: "Autour", projects: "Projets",
  },
  en: {
    mooring: "Mooring", marinas: "Marinas", capitaineries: "Harbour master", wpi: "WPI ports", anchorages: "Anchorages",
    services: "Services", fuel: "Fuel", water: "Water",
    around: "Around", projects: "Projects",
  },
};

function googleMapsUrl(lat, lon) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
  return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(5)}%2C${lo.toFixed(5)}`;
}

export function visibleSections(sections) {
  const out = {};
  Object.entries(sections || {}).forEach(([key, value]) => {
    if (key === "formalities") return;
    out[key] = value;
  });
  return out;
}

function label(key, lang) {
  return LABELS[lang]?.[key] || key;
}

export const EscaleSheet = memo(function EscaleSheet({
  stop,
  fiche,
  loading,
  error,
  onClose,
  pledge,
  onPledgeAuthorized,
}) {
  const { t, i18n } = useTranslation();
  if (!stop) return null;
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const sections = visibleSections(fiche?.sections);
  const keys = Object.keys(sections);

  return (
    <div data-testid="escale-sheet" className="escale-sheet">
      <div className="escale-sheet-head">
        <div>
          <div className="escale-kicker">{t("sheet.title")}</div>
          <strong>{stop.name}</strong>
        </div>
        {onClose ? (
          <button type="button" data-testid="escale-close" onClick={onClose} aria-label={t("sheet.close")}>
            ×
          </button>
        ) : null}
      </div>
      {loading ? <p className="hint">{t("sheet.loading")}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
      {!loading && fiche && !keys.length ? <p className="hint">{t("sheet.empty")}</p> : null}
      {keys.map((section) => (
        <div key={section}>
          <div className="escale-kicker">{label(section, lang)}</div>
          {Object.entries(sections[section] || {}).map(([sub, items]) => (
            Array.isArray(items) ? (
              <div key={sub}>
                <div className="hint">{label(sub, lang)}</div>
                <ul className="escale-items">
                  {items.map((item, index) => {
                    const site = item.url || item.visit_url || null;
                    const maps = googleMapsUrl(item.lat, item.lon);
                    return (
                      <li key={`${item.name}-${index}`}>
                        <span>{item.name}</span>
                        {Number.isFinite(item.nm) ? <span className="hint"> {item.nm} nm</span> : null}
                        {item.phone ? <a href={`tel:${item.phone}`}>{item.phone}</a> : null}
                        {site ? <a href={site} target="_blank" rel="noopener noreferrer">↗</a> : null}
                        {maps ? <a href={maps} target="_blank" rel="noopener noreferrer">◎</a> : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null
          ))}
        </div>
      ))}
      {pledge ? (
        <div className="pledge-form">
          <p className="hint">{t("pledge.intent")}</p>
          <label>
            {t("pledge.amount")}
            <input value={pledge.amount} onChange={(event) => pledge.onAmount(event.target.value)} />
          </label>
          <label>
            {t("pledge.description")}
            <input value={pledge.description} onChange={(event) => pledge.onDescription(event.target.value)} />
          </label>
          <label>
            {t("pledge.milestone")}
            <input value={pledge.milestoneId} onChange={(event) => pledge.onMilestoneId(event.target.value)} />
          </label>
          <label>
            {t("pledge.contributor")}
            <input value={pledge.contributor} onChange={(event) => pledge.onContributor(event.target.value)} />
          </label>
          <PledgeButton
            values={{
              amount_eur: pledge.amount,
              description: pledge.description,
              milestone_id: pledge.milestoneId,
              contributor: pledge.contributor.trim() || undefined,
            }}
            onAuthorized={onPledgeAuthorized}
          />
        </div>
      ) : null}
    </div>
  );
});

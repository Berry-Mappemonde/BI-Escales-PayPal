/**
 * Fiche d'escale. Dérivée de naviguide-escales/src/components/EscaleSheet.jsx.
 * Le paragraphe narratif, le badge LLM et la section formalités (PoE) sont retirés.
 * Le bouton PayPal (PledgeButton, PR #2) est hébergé ici.
 * googleMapsUrl est la fonction du même nom dans engine/briefingLinks.js.
 */
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainReview } from "../api/escales";
import { HELLOASSO_MEMBERSHIP_URL } from "../config/helloasso.js";
import { PledgeButton } from "./PledgeButton";

const STOP_KINDS = ["mile", "night", "meal", "care", "common_fund"];
const FIXED_AMOUNT = { night: "60.00", meal: "60.00", care: "40.00" };

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

function FundLines({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div>
      <div className="hint">{title}</div>
      <ul className="escale-items">
        {rows.map((row, index) => (
          <li key={row.id || `${row.kind}-${index}`}>
            <span>{row.amount_eur} {row.currency || "EUR"}</span>
            {row.description ? <span> — {row.description}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const EscaleSheet = memo(function EscaleSheet({
  stop,
  fiche,
  loading,
  error,
  onClose,
  pledge,
  onPledgeAuthorized,
  fund,
  fundError,
  adminKey,
}) {
  const { t, i18n } = useTranslation();
  const [review, setReview] = useState(null);
  const [reviewError, setReviewError] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  if (!stop) return null;
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const sections = visibleSections(fiche?.sections);
  const keys = Object.keys(sections);
  const reviewMilestone = stop.milestoneId || pledge?.milestoneId || "";
  const treasurerKey = (adminKey || "").trim();

  const onCaptainReview = async () => {
    if (!reviewMilestone) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      const row = await captainReview(reviewMilestone, treasurerKey || undefined);
      const stored = treasurerKey ? row : { ...row, pending_authorizations: undefined };
      setReview(stored);
    } catch (err) {
      setReview(null);
      setReviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setReviewBusy(false);
    }
  };

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
      <section className="fund-panel" data-testid="common-fund">
        <div className="escale-kicker">{t("fund.heading")}</div>
        {fund ? (
          <p>
            {t("fund.figures", {
              balance: fund.balance_eur,
              currency: fund.currency,
              income: fund.income_eur,
              spending: fund.spending_eur,
            })}
          </p>
        ) : null}
        {fund?.overdrawn ? <p className="notice warn">{t("fund.overdrawn")}</p> : null}
        {fundError ? <p className="hint">{t("fund.missing")}</p> : null}
        {fund && !fund.income?.length && !fund.spending?.length ? <p className="hint">{t("fund.empty")}</p> : null}
        <FundLines title={t("fund.income")} rows={fund?.income} />
        <FundLines title={t("fund.spending")} rows={fund?.spending} />
        <p className="fund-line">
          {t("fund.line")}{" "}
          <a href={HELLOASSO_MEMBERSHIP_URL} target="_blank" rel="noreferrer">{t("fund.helloasso")}</a>
        </p>
      </section>
      <button
        type="button"
        data-testid="captain-review"
        onClick={() => void onCaptainReview()}
        disabled={reviewBusy || !reviewMilestone}
      >
        {t("sheet.captainReview")}
      </button>
      {reviewError ? <p className="notice error">{reviewError}</p> : null}
      {review ? (
        <div data-testid="captain-review-result">
          <p>{review.proposal}</p>
          {review.justification ? <p>{review.justification}</p> : null}
          {review.pending_authorizations?.length ? (
            <ul data-testid="pending-authorizations">
              {review.pending_authorizations.map((row) => (
                <li key={row.authorization_id || row.pledge_id}>
                  {row.authorization_id} {row.amount_eur} {row.currency}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {pledge ? (
        <div className="pledge-form">
          <p className="hint">{t("pledge.intent")}</p>
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
              amount_eur: FIXED_AMOUNT[pledge.kind] || pledge.amount,
              description: pledge.description,
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

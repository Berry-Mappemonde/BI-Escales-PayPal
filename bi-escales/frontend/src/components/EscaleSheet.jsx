/**
 * Fiche d'escale. Dérivée de naviguide-escales/src/components/EscaleSheet.jsx.
 * Le paragraphe narratif, le badge LLM et la section formalités (PoE) sont retirés.
 * Le bouton PayPal (PledgeButton, PR #2) est hébergé ici.
 * googleMapsUrl est la fonction du même nom dans engine/briefingLinks.js.
 */
import { memo, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { PledgeButton } from "./PledgeButton";
import {
  cabinLegMilestoneId,
  pledgeAmountReadOnly,
  pledgeOrderAmount,
} from "../pledge/stopPledgeAmount.js";
import {
  formatEurAmount,
  formatScheduleDate,
  fundTotals,
  isMilestoneCancelled,
  logbookLine,
  logbookUpTo,
  stopStatus,
  stopTimeline,
} from "../voyage/stopStatus.js";
import { StopStatusChip } from "./stop/StopStatusChip.jsx";
import { MileCertificateDownload } from "./MileCertificateDownload";
import { useStopContext } from "./stop/useStopContext.js";
import { evaluateGooglePlaceLink, googleMapsSearchUrl } from "../marinas/marinaPlaceLink.js";

const STOP_KINDS = ["mile", "berth", "night", "meal", "care", "cabin_leg", "common_fund"];

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
  priceCatalog,
  schedule,
  onPledgeAuthorized,
  arrivalIso,
  logbookEntries,
}) {
  const { t, i18n } = useTranslation();
  const [quantity, setQuantity] = useState(1);
  const [receiptPledge, setReceiptPledge] = useState(null);
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  const context = useStopContext(stop?.milestoneId);
  const { refresh } = context;
  // PledgeButton re-renders the PayPal buttons when this changes, so it must stay stable.
  const onAuthorized = useCallback(
    (authorized) => {
      refresh();
      onPledgeAuthorized?.(authorized);
      if (
        authorized?.kind === "mile"
        && ["authorized", "vaulted", "captured"].includes(authorized.status)
      ) {
        setReceiptPledge(authorized);
      }
    },
    [refresh, onPledgeAuthorized],
  );
  if (!stop) return null;
  const sections = visibleSections(fiche?.sections);
  const keys = Object.keys(sections);
  const pledgeDescription = pledge
    ? `${stop.name} — ${t(`pledge.kinds.${pledge.kind}`)}`
    : "";
  const perUnit = pledge && ["mile", "night", "meal", "care", "berth", "cabin_leg"].includes(pledge.kind);
  const orderAmount = pledge ? pledgeOrderAmount(pledge.kind, pledge.amount, priceCatalog, perUnit ? quantity : undefined) : "";
  const readOnlyAmount = pledge ? perUnit || pledgeAmountReadOnly(pledge.kind, priceCatalog) : false;
  const pledgeMilestoneId = pledge
    ? (pledge.kind === "cabin_leg"
      ? cabinLegMilestoneId(schedule, pledge.milestoneId, stop.name) || pledge.milestoneId
      : pledge.milestoneId)
    : "";
  const { startIso, departureIso } = stopTimeline(schedule, stop);
  const arrivalLabel = formatScheduleDate(arrivalIso, lang);
  const departureLabel = formatScheduleDate(departureIso, lang);
  const milestone = context.milestones?.find((row) => row.id === stop.milestoneId);
  const cancelled = isMilestoneCancelled(milestone);
  // Status needs the clock and the milestones; if either call failed the chip is left out.
  const status = context.milestones
    ? stopStatus({ now: context.now, arrivalIso, startIso, cancelled })
    : null;
  const { heldEur, capturedEur } = fundTotals(context.fund);
  const logLines = logbookUpTo(logbookEntries, context.now).map((entry) => logbookLine(entry, lang));

  return (
    <div data-testid="escale-sheet" className="escale-sheet">
      <div className="escale-sheet-head">
        <div>
          <div className="escale-kicker stop-identity">
            {stop.flags?.map((src) => <img key={src} src={src} alt="" />)}
            {t("sheet.title")}
          </div>
          <div className="stop-title">
            <h2>{stop.name}</h2>
            {status ? <StopStatusChip status={status} /> : null}
          </div>
        </div>
        {onClose ? (
          <button type="button" data-testid="escale-close" onClick={onClose} aria-label={t("sheet.close")}>
            ×
          </button>
        ) : null}
      </div>
      {arrivalLabel || departureLabel || heldEur || capturedEur ? (
        <div className="stop-section stop-summary">
          {arrivalLabel || departureLabel ? (
            <dl className="stop-rows">
              {arrivalLabel ? (
                <div data-testid="escale-estimated-arrival">
                  <dt>{t("stopPanel.scheduledArrival")}</dt>
                  <dd>{arrivalLabel}</dd>
                </div>
              ) : null}
              {departureLabel ? (
                <div data-testid="stop-scheduled-departure">
                  <dt>{t("stopPanel.scheduledDeparture")}</dt>
                  <dd>{departureLabel}</dd>
                </div>
              ) : null}
            </dl>
          ) : null}
          {heldEur || capturedEur ? (
            <p className="stop-money" data-testid="stop-money">
              {heldEur ? <span className="stop-held">{t("stopPanel.held", { amount: formatEurAmount(heldEur, lang) })}</span> : null}
              {heldEur && capturedEur ? " · " : null}
              {capturedEur ? t("stopPanel.captured", { amount: formatEurAmount(capturedEur, lang) }) : null}
            </p>
          ) : null}
        </div>
      ) : null}
      {pledge && !cancelled ? (
        <section className="stop-section stop-next" data-testid="stop-next-step">
          <h3 className="stop-next-title">{t("stopPanel.backThisLeg")}</h3>
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
            <div className="pledge-calculation">
              {perUnit ? <label>
                {t("pledge.quantity")}
                <input type="number" min={1} max={1000} step={1} data-testid="pledge-quantity"
                  value={quantity} onChange={(event) => setQuantity(Math.max(1, Math.min(1000, Math.trunc(Number(event.target.value) || 1))))} />
              </label> : null}
              <label>
                {t("pledge.amount")}
                <input
                  data-testid="pledge-amount"
                  value={orderAmount}
                  readOnly={readOnlyAmount}
                  onChange={(event) => {
                    if (!readOnlyAmount) pledge.onAmount(event.target.value);
                  }}
                />
              </label>
            </div>
            <label>
              {t("pledge.contributor")}
              <input value={pledge.contributor} onChange={(event) => pledge.onContributor(event.target.value)} />
            </label>
            <div className="stop-checkout">
              <h4>{t("stopPanel.checkout")}</h4>
              <PledgeButton
                values={{
                  amount_eur: orderAmount,
                  quantity: perUnit ? quantity : undefined,
                  description: pledgeDescription,
                  milestone_id: pledgeMilestoneId,
                  contributor: pledge.contributor.trim() || undefined,
                  kind: pledge.kind,
                  target_id: pledge.kind === "cabin_leg" ? pledgeMilestoneId : pledge.milestoneId,
                }}
                onAuthorized={onAuthorized}
              />
            </div>
          </div>
          <MileCertificateDownload pledge={receiptPledge} contributor={pledge.contributor} />
          <h4 className="money-heading">{t("stopPanel.moneyHeading")}</h4>
          {pledge.kind === "common_fund" ? (
            <p className="stop-note" data-testid="stop-money-rule">{t("stopPanel.ruleCommonFund")}</p>
          ) : (
            <ol className="money-steps" data-testid="stop-money-rule">
              <li>{t("stopPanel.ruleHeld")} </li>
              <li>{t(pledge.kind === "cabin_leg" ? "stopPanel.ruleCabin" : "stopPanel.ruleCaptured")} </li>
              <li>{t(pledge.kind === "cabin_leg" ? "stopPanel.ruleReleasedCabin" : "stopPanel.ruleReleased")}</li>
            </ol>
          )}
        </section>
      ) : null}
      {pledge && cancelled ? (
        <div className="stop-section">
          <p className="stop-cancelled" data-testid="stop-cancelled-note">
            {t("stopPanel.cancelledNote")}
          </p>
        </div>
      ) : null}
      {context.now ? (
        <details className="stop-more" data-testid="escale-logbook">
          <summary>{t("sheet.logbookTitle")}</summary>
          <div className="stop-more-body">
            {logLines.length ? (
              <>
                <p className="stop-note">{t("stopPanel.logbookNote")}</p>
                <ul className="escale-items">
                  {logLines.map((line, index) => (
                    <li key={`${line}-${index}`}>{line}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="stop-note">{t("stopPanel.logbookEmpty")}</p>
            )}
          </div>
        </details>
      ) : null}
      {loading ? <p className="rail-loading" role="status">{t("sheet.loading")}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
      {!loading && fiche ? (
        <details className="stop-more" data-testid="stop-port-info">
          <summary>{t("stopPanel.portInfo")}</summary>
          <div className="stop-more-body">
            {!keys.length ? <p className="hint">{t("sheet.empty")}</p> : null}
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
          </div>
        </details>
      ) : null}
    </div>
  );
});

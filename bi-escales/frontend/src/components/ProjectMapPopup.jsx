/**
 * PayPal pledge block inside a Leaflet project marker popup.
 * Source: Clément lot 4 Nov 2025 — project popup PayPal on the map (plan canvas).
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { parseProjectPledgeAmount } from "../projects/projectPledgeAmount.js";
import { PledgeButton } from "./PledgeButton";

const MIN_EUR = "1.00";

export function ProjectMapPopup({ properties, contributorDefault = "", onAuthorized }) {
  const { t, i18n } = useTranslation();
  const props = properties || {};
  const [amount, setAmount] = useState(MIN_EUR);
  const [who, setWho] = useState(contributorDefault || "");
  const title = props.title || props.id || "";
  const description = String(props.description || "").trim();
  const siteUrl = String(props.url || "").trim();
  const parsed = parseProjectPledgeAmount(amount);
  const pledgeDescription = t("projects.pledgeDescription", { title: props.title || props.id || "" });
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";

  return (
    <div className="project-map-popup-inner" data-testid="project-map-popup">
      <h3 className="project-map-popup-title">{title}</h3>
      {description ? (
        <p className="project-map-popup-desc" data-testid="project-map-description">
          {description}
        </p>
      ) : (
        <p className="hint" data-testid="project-map-description-empty">
          {t("projects.noDescription")}
        </p>
      )}
      {siteUrl ? (
        <p className="project-map-popup-link-row">
          <a
            href={siteUrl}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="project-map-site-link"
          >
            {t("projects.visitSite")}
          </a>
        </p>
      ) : null}
      <div className="project-map-popup-pledge" data-testid="project-map-pledge-form">
        <label>
          {t("pledge.amount")}
          <input
            type="text"
            inputMode="decimal"
            data-testid="project-map-pledge-amount"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label>
          {t("pledge.contributor")}
          <input
            type="text"
            data-testid="project-map-pledge-contributor"
            value={who}
            onChange={(event) => setWho(event.target.value)}
          />
        </label>
        {parsed.kind === "invalid" ? (
          <p className="notice warn" data-testid="project-map-amount-invalid">
            {t("projects.invalidAmount")}
          </p>
        ) : null}
        {parsed.kind === "empty" || parsed.kind === "below_min" ? (
          <p className="notice warn" data-testid="project-map-amount-min">
            {t("projects.minAmount")}
          </p>
        ) : null}
        <PledgeButton
          values={{
            amount_eur: parsed.apiAmount || MIN_EUR,
            description: pledgeDescription,
            milestone_id: "",
            contributor: who.trim() || undefined,
            kind: "project_pledge",
            target_id: props.id,
            lang,
          }}
          disabled={parsed.kind !== "ok"}
          onAuthorized={onAuthorized}
        />
      </div>
    </div>
  );
}

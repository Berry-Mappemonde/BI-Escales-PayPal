import { useTranslation } from "react-i18next";
import { normalizeChannel3ProductUrl } from "../gear/channel3ProductUrl.js";

/**
 * Public crowdfunding progress toward a gear/project goal (CAPTURE donations).
 */
export function ProjectFundProgress({ properties, fund }) {
  const { t } = useTranslation();
  const goal = String(
    fund?.goal_eur ||
      fund?.goal_amount ||
      properties?.goal_eur ||
      properties?.channel3_price ||
      "",
  ).trim();
  if (!goal) return null;
  const goalCurrency = String(
    fund?.goal_currency ||
      properties?.goal_currency ||
      properties?.channel3_currency ||
      (fund?.goal_eur || properties?.goal_eur ? "EUR" : ""),
  ).trim();
  const pctRaw = fund?.funded_pct;
  const pct = pctRaw == null ? null : Number(pctRaw);
  const amount = fund?.amount_eur ?? "0.00";
  const amountCurrency = fund?.currency ?? "EUR";
  const buyUrl = normalizeChannel3ProductUrl(fund?.channel3_buy_url || properties?.channel3_buy_url);
  const imageUrl = String(fund?.channel3_image_url || properties?.channel3_image_url || "").trim();
  const fullyFunded = Boolean(fund?.fully_funded);

  return (
    <div className="project-fund-progress" data-testid="project-fund-progress">
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={properties?.channel3_product_name || properties?.title || ""}
          className="gear-channel3-photo"
          data-testid="gear-channel3-photo"
        />
      ) : null}
      <p className="hint" data-testid="project-fund-goal">
        {t("projects.goalProgress", {
          amount,
          amountCurrency,
          goal,
          goalCurrency: goalCurrency || "EUR",
          pct: pct == null ? "—" : pct,
        })}
      </p>
      <div className="gauge">
        <div className="gauge-track">
          <div
            className="gauge-fill tone-cap"
            style={{ width: `${pct == null ? 0 : Math.min(100, pct)}%` }}
          />
        </div>
      </div>
      {fullyFunded && buyUrl ? (
        <p data-testid="gear-channel3-buy">
          <a href={buyUrl} target="_blank" rel="noopener noreferrer">
            {t("projects.buyViaChannel3")}
          </a>
        </p>
      ) : null}
    </div>
  );
}

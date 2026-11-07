import { useTranslation } from "react-i18next";

/**
 * Public crowdfunding progress toward a gear/project goal (CAPTURE donations).
 */
export function ProjectFundProgress({ properties, fund }) {
  const { t } = useTranslation();
  const goal = String(fund?.goal_eur || properties?.goal_eur || "").trim();
  if (!goal) return null;
  const pct = Number(fund?.funded_pct ?? 0);
  const amount = fund?.amount_eur ?? "0.00";
  const currency = fund?.currency ?? "EUR";
  const buyUrl = String(fund?.channel3_buy_url || properties?.channel3_buy_url || "").trim();
  const imageUrl = String(fund?.channel3_image_url || properties?.channel3_image_url || "").trim();
  const fullyFunded = Boolean(fund?.fully_funded) || pct >= 100;

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
        {t("projects.goalProgress", { amount, goal, currency, pct })}
      </p>
      <div className="gauge">
        <div className="gauge-track">
          <div className="gauge-fill tone-cap" style={{ width: `${Math.min(100, pct)}%` }} />
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

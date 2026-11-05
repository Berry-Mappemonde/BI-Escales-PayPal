/**
 * PayPal berth reservation in a marina map popup (30 EUR simulation, capture on arrival).
 * Pattern: ``MarinasPanel.jsx`` reserve block + ``ProjectMapPopup.jsx`` Leaflet popup shell.
 */
import { useTranslation } from "react-i18next";
import { PledgeButton } from "./PledgeButton";

const BERTH_EUR = "30.00";

export function MarinaMapPopup({ properties, milestoneId, contributorDefault = "", onAuthorized }) {
  const { t } = useTranslation();
  const props = properties || {};
  const name = props.name || t("marinas.unnamed");
  const maps = props.maps_url || null;
  const website = props.website || null;

  return (
    <div className="marina-map-popup-inner" data-testid="marina-map-popup">
      <h3 className="marina-map-popup-title">{name}</h3>
      {props.safe_google_place ? (
        <p className="hint marina-map-verified" data-testid="marina-map-verified">
          {t("marinas.legendVerified")}
        </p>
      ) : null}
      <div className="marina-map-popup-links">
        {website ? (
          <a href={website} target="_blank" rel="noopener noreferrer" data-testid="marina-map-website">
            {t("sheet.marina.website")} ↗
          </a>
        ) : null}
        {maps ? (
          <a href={maps} target="_blank" rel="noopener noreferrer" data-testid="marina-map-maps">
            {t("sheet.marina.maps")} ◎
          </a>
        ) : null}
      </div>
      <div data-testid="marina-map-reserve" data-kind="berth">
        <p className="hint">{t("marinas.reservePrice")}</p>
        <PledgeButton
          values={{
            amount_eur: BERTH_EUR,
            description: t("marinas.reserveDescription", { name }),
            milestone_id: milestoneId || "",
            contributor: contributorDefault || undefined,
            kind: "berth",
            target_id: milestoneId || "",
          }}
          disabled={!milestoneId}
          onAuthorized={onAuthorized}
        />
      </div>
    </div>
  );
}

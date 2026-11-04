/** Channel3 onboard gear list — optional module (ESCALES_CHANNEL3_ENABLED + CHANNEL3_API_KEY). */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchChannel3Gear } from "../api/escales";
import { PledgeButton } from "./PledgeButton";

export function Channel3GearPanel({ milestoneId, onAuthorized }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    void fetchChannel3Gear()
      .then((payload) => {
        if (!cancel) setItems(payload.items || []);
      })
      .catch((e) => {
        if (!cancel) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancel = true;
    };
  }, []);

  if (error) return null;
  if (!items.length) return null;

  return (
    <section className="panel channel3-gear" data-testid="channel3-gear-panel">
      <h2>{t("channel3.heading")}</h2>
      <p className="hint">{t("channel3.hint")}</p>
      <ul className="channel3-gear-list">
        {items.map((item) => (
          <li key={item.id} data-testid={`channel3-item-${item.id}`}>
            {item.image_url ? (
              <img src={item.image_url} alt="" width={64} height={64} loading="lazy" />
            ) : null}
            <div>
              <strong>{item.title}</strong>
              <p>
                {item.amount_eur} {item.currency}
                {item.buy_url ? (
                  <>
                    {" · "}
                    <a href={item.buy_url} target="_blank" rel="noreferrer">
                      {t("channel3.productLink")}
                    </a>
                  </>
                ) : null}
              </p>
              <PledgeButton
                values={{
                  amount_eur: item.amount_eur,
                  description: item.title,
                  milestone_id: milestoneId,
                  kind: "gear",
                  target_id: item.id,
                }}
                onAuthorized={onAuthorized}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

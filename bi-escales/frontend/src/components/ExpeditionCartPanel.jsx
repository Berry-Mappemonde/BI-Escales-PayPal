import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchExpeditionCart } from "../api/escales";
import { Channel3Thumb } from "./Channel3Thumb";

function formatPrice(line, t) {
  const amount = String(line?.amount_eur || "").trim();
  if (amount) {
    const currency = String(line?.currency || "EUR").trim();
    let text = `${amount} ${currency}`;
    if (line?.simulated) {
      text += ` (${t("pledge.simulatedPrice")})`;
    }
    return text;
  }
  const label = String(line?.price_label || "").trim();
  if (label) return label;
  return t("cart.priceUnavailable");
}

/**
 * `images` maps a gear line's id to its Channel3 picture. The cart payload has
 * no picture of its own; the gear projects the page already loaded do.
 */
export default function ExpeditionCartPanel({ images = {} }) {
  const { t, i18n } = useTranslation();
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [cart, setCart] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    void fetchExpeditionCart(lang)
      .then((payload) => {
        if (!cancelled) setCart(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [lang]);

  const lines = cart?.lines || [];

  return (
    <section className="panel expedition-cart" data-testid="expedition-cart">
      <h2>{t("cart.heading")}</h2>
      {error ? <p className="notice error">{error}</p> : null}
      {!cart && !error ? <p className="hint">{t("cart.loading")}</p> : null}
      {lines.length ? (
        <table className="expedition-cart-table" data-testid="expedition-cart-table">
          <thead>
            <tr>
              <th scope="col">{t("cart.item")}</th>
              <th scope="col">{t("cart.price")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr
                key={`${line.kind}-${line.id}`}
                data-testid="expedition-cart-row"
                data-kind={line.kind}
              >
                <td>
                  <span className="channel3-line">
                    {line.kind === "gear" ? (
                      <Channel3Thumb src={images[line.id]} title={line.description} size="sm" testId="expedition-cart-photo" />
                    ) : null}
                    <span>{line.description}</span>
                  </span>
                </td>
                <td data-testid="expedition-cart-price">{formatPrice(line, t)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

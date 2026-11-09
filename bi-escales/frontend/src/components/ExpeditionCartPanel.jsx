import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchExpeditionCart } from "../api/escales";

function formatPrice(line, t) {
  const amount = String(line?.amount_eur || "").trim();
  if (amount) {
    const currency = String(line?.currency || "EUR").trim();
    return `${amount} ${currency}`;
  }
  const label = String(line?.price_label || "").trim();
  if (label) return label;
  return t("cart.priceUnavailable");
}

export default function ExpeditionCartPanel() {
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
                <td>{line.description}</td>
                <td data-testid="expedition-cart-price">{formatPrice(line, t)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

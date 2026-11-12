import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchRecentWebhooks, type WebhookOutcomeRow } from "../api/escales";

export interface TreasurerWebhookPanelProps {
  adminKey: string;
}

/** Rows listed in the table; the status line above counts every notification recorded. */
const ROWS_SHOWN = 20;

/** What the server did with a notification, in words. Unknown values are shown as they are. */
const OUTCOMES = new Set(["accepted", "duplicate", "rejected"]);

/**
 * PayPal notifications (webhooks), read-only: when the last one came in, how many
 * were recorded, then the most recent ones. Treasurer key only, like the route.
 */
export function TreasurerWebhookPanel({ adminKey }: TreasurerWebhookPanelProps) {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<WebhookOutcomeRow[]>([]);
  const [total, setTotal] = useState(0);
  // False until the first answer: "none received yet" must not flash before it.
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const key = adminKey.trim();
    if (!key) {
      setRows([]);
      setTotal(0);
      setLoaded(false);
      return;
    }
    setError(null);
    try {
      // Newest first, as the server sends them.
      const events = await fetchRecentWebhooks(key);
      setRows(events.slice(0, ROWS_SHOWN));
      setTotal(events.length);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [adminKey]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!adminKey.trim()) return null;

  const locale = i18n.language?.startsWith("fr") ? "fr-FR" : "en-GB";
  const when = (iso: string | undefined) => {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return iso || "—";
    const text = new Intl.DateTimeFormat(locale, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "UTC",
    }).format(at);
    return `${text} UTC`;
  };
  const outcome = (value: string | undefined) =>
    value && OUTCOMES.has(value) ? t(`treasurer.webhooks.outcomes.${value}`) : value || "—";
  const last = rows[0];

  return (
    <section className="panel treasurer-webhooks" data-testid="treasurer-webhook-panel">
      <h3>{t("treasurer.webhooks.heading")}</h3>
      <p className="hint">{t("treasurer.webhooks.lead")}</p>
      {error ? <p className="notice error">{error}</p> : null}
      {last ? (
        <p className="webhook-status" data-testid="paypal-notifications-status">
          <strong>{t("treasurer.webhooks.lastReceived", { when: when(last.time) })}</strong>
          {last.event_type ? ` · ${last.event_type}` : ""}
          {last.outcome ? ` · ${outcome(last.outcome)}` : ""}
          <br />
          <span data-testid="paypal-notifications-count">{t("treasurer.webhooks.count", { count: total })}</span>
        </p>
      ) : null}
      {loaded && !last ? (
        <p className="hint" data-testid="paypal-notifications-status">{t("treasurer.webhooks.empty")}</p>
      ) : null}
      <button type="button" onClick={() => void refresh()}>
        {t("treasurer.webhooks.refresh")}
      </button>
      {rows.length ? (
        <table className="fallback-table">
          <caption className="hint">{t("treasurer.webhooks.latest", { count: rows.length })}</caption>
          <thead>
            <tr>
              <th scope="col">{t("treasurer.webhooks.time")}</th>
              <th scope="col">{t("treasurer.webhooks.event")}</th>
              <th scope="col">{t("treasurer.webhooks.outcome")}</th>
              <th scope="col">{t("treasurer.webhooks.pledge")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.transmission_id}-${row.time}`} data-testid="webhook-row">
                <td>
                  <time dateTime={row.time || undefined}>{when(row.time)}</time>
                </td>
                <td>{row.event_type || "—"}</td>
                <td>{outcome(row.outcome)}</td>
                <td title={row.pledge_id || undefined}>{row.pledge_id ? row.pledge_id.slice(0, 8) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

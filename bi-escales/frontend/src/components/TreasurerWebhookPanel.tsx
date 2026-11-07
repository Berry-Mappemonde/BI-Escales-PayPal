import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchRecentWebhooks, type WebhookOutcomeRow } from "../api/escales";

export interface TreasurerWebhookPanelProps {
  adminKey: string;
}

export function TreasurerWebhookPanel({ adminKey }: TreasurerWebhookPanelProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<WebhookOutcomeRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const key = adminKey.trim();
    if (!key) {
      setRows([]);
      return;
    }
    setError(null);
    try {
      const events = await fetchRecentWebhooks(key);
      setRows(events.slice(0, 20));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [adminKey]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!adminKey.trim()) return null;

  return (
    <section className="panel treasurer-webhooks" data-testid="treasurer-webhook-panel">
      <h2>{t("treasurer.webhooks.heading")}</h2>
      <button type="button" onClick={() => void refresh()}>
        {t("treasurer.refresh")}
      </button>
      {error ? <p className="notice error">{error}</p> : null}
      {rows.length === 0 ? <p className="hint">{t("treasurer.webhooks.empty")}</p> : null}
      <table className="fallback-table">
        <thead>
          <tr>
            <th>{t("treasurer.webhooks.time")}</th>
            <th>{t("treasurer.webhooks.event")}</th>
            <th>{t("treasurer.webhooks.outcome")}</th>
            <th>{t("treasurer.webhooks.pledge")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.transmission_id}-${row.time}`} data-testid="webhook-row">
              <td>{row.time || "—"}</td>
              <td>{row.event_type || "—"}</td>
              <td>{row.outcome || "—"}</td>
              <td>{row.pledge_id || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

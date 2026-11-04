import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { listFinanceEntries, type FinanceEntry } from "../api/escales";

export interface FinanceLedgerPanelProps {
  adminKey: string;
}

export function FinanceLedgerPanel({ adminKey }: FinanceLedgerPanelProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<FinanceEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!adminKey.trim()) {
      setError(t("finance.needsKey"));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setEntries(await listFinanceEntries(adminKey.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [adminKey, t]);

  return (
    <section className="panel finance-ledger" data-testid="finance-ledger-panel">
      <h2>{t("finance.heading")}</h2>
      <p className="hint">{t("finance.hint")}</p>
      <button type="button" onClick={() => void load()} disabled={loading}>
        {t("finance.load")}
      </button>
      {error ? <p className="notice error">{error}</p> : null}
      {entries.length === 0 ? (
        <p className="hint">{t("finance.empty")}</p>
      ) : (
        <table className="fallback-table">
          <thead>
            <tr>
              <th>{t("finance.kind")}</th>
              <th>{t("finance.pledge")}</th>
              <th>{t("finance.detail")}</th>
              <th>{t("finance.at")}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((row, index) => (
              <tr key={`${row.kind}-${row.at}-${index}`}>
                <td>{row.kind}</td>
                <td>{row.pledge_id ?? "—"}</td>
                <td>
                  <code>{JSON.stringify(row.detail ?? {})}</code>
                </td>
                <td>{row.at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

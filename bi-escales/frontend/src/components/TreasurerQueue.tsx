import { useState } from "react";
import { useTranslation } from "react-i18next";
import { capturePledge, voidPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { isQueuedPledge } from "../hooks/queueFilter";
import { PayPalStatusBadge } from "./PayPalStatusBadge";

export interface TreasurerQueueProps {
  pledges: PublicPledge[];
  loading?: boolean;
  error?: string | null;
  needsKey?: boolean;
  adminKey: string;
  onRefresh: () => void;
  onUpdated: (pledge: PublicPledge) => void;
}

export function TreasurerQueue({
  pledges,
  loading,
  error,
  needsKey,
  adminKey,
  onRefresh,
  onUpdated,
}: TreasurerQueueProps) {
  const { t } = useTranslation();
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const queue = pledges.filter((p) => isQueuedPledge(p.status));

  const runAction = async (pledgeId: string, action: "capture" | "void") => {
    if (!adminKey.trim()) {
      setActionError("Admin key required");
      return;
    }
    setBusyId(pledgeId);
    setActionError(null);
    try {
      const updated =
        action === "capture"
          ? await capturePledge(pledgeId, adminKey.trim())
          : await voidPledge(pledgeId, adminKey.trim());
      onUpdated(updated);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="panel treasurer-queue">
      <h2>{t("treasurer.heading")}</h2>
      <p className="hint">{t("treasurer.adminKeyHint")}</p>
      <button type="button" onClick={onRefresh} disabled={loading}>
        {t("treasurer.refresh")}
      </button>
      {loading ? (
        <p className="hint" role="status" data-testid="queue-loading">
          {t("treasurer.loading")}
        </p>
      ) : null}
      {error ? (
        <p className="notice error" data-testid="queue-error">
          {t("treasurer.loadError")}: {error}
        </p>
      ) : null}
      {actionError ? (
        <p className="notice error" data-testid="queue-action-error">
          {actionError}
        </p>
      ) : null}

      {needsKey ? (
        <p className="hint" data-testid="queue-needs-key">
          {t("treasurer.queueNeedsKey")}
        </p>
      ) : loading ? null : queue.length === 0 ? (
        <p className="hint" data-testid="queue-empty">
          {t("treasurer.queueEmpty")}
        </p>
      ) : (
        <table className="fallback-table">
          <thead>
            <tr>
              <th>{t("treasurer.status")}</th>
              <th>{t("treasurer.amount")}</th>
              <th>{t("treasurer.description")}</th>
              <th>{t("treasurer.milestone")}</th>
              <th>{t("treasurer.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((p) => (
              <tr key={p.id} data-testid={`queue-row-${p.id}`}>
                <td>
                  <PayPalStatusBadge pledge={p} />
                </td>
                <td>
                  {p.amount_eur} {p.currency}
                </td>
                <td>{p.description}</td>
                <td>{p.milestone_id}</td>
                <td className="actions">
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => void runAction(p.id, "capture")}
                  >
                    {t("treasurer.capture")}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busyId === p.id}
                    onClick={() => void runAction(p.id, "void")}
                  >
                    {t("treasurer.void")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { captainReview, capturePledge, voidPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { featureAgGridEnabled } from "../config/features";
import { isQueuedPledge } from "../hooks/queueFilter";
import type { TreasurerQueueAgProps } from "./TreasurerQueueAg";

const LazyTreasurerQueueAg = lazy(() => import("./TreasurerQueueAg"));

export interface TreasurerQueueProps {
  pledges: PublicPledge[];
  loading?: boolean;
  error?: string | null;
  needsKey?: boolean;
  adminKey: string;
  onRefresh: () => void;
  onUpdated: (pledge: PublicPledge) => void;
}

function FallbackQueueTable({
  queue,
  verdicts,
  busyId,
  approveLabel,
  onApprove,
}: {
  queue: PublicPledge[];
  verdicts: Record<string, string>;
  busyId: string | null;
  approveLabel: string;
  onApprove: (pledgeId: string, action: "capture" | "void") => void;
}) {
  const { t } = useTranslation();
  return (
    <table className="fallback-table" data-testid="treasurer-queue-fallback-table">
      <thead>
        <tr>
          <th>{t("treasurer.status")}</th>
          <th>{t("treasurer.amount")}</th>
          <th>{t("treasurer.description")}</th>
          <th>{t("treasurer.milestone")}</th>
          <th>{t("treasurer.verdict")}</th>
          <th>{t("treasurer.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {queue.map((p) => (
          <tr key={p.id} data-testid={`queue-row-${p.id}`}>
            <td>{p.status}</td>
            <td>
              {p.amount_eur} {p.currency}
            </td>
            <td>{p.description}</td>
            <td>{p.milestone_id}</td>
            <td data-testid={`verdict-${p.id}`}>{verdicts[p.milestone_id] || ""}</td>
            <td className="actions">
              <button
                type="button"
                data-testid={`approve-${p.id}`}
                disabled={
                  busyId === p.id || !["capture", "void"].includes(verdicts[p.milestone_id] || "")
                }
                onClick={() => void onApprove(p.id, verdicts[p.milestone_id] as "capture" | "void")}
              >
                {approveLabel}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OptionalAgQueue({
  fallback,
  ...props
}: TreasurerQueueAgProps & { fallback: ReactNode }) {
  return (
    <Suspense fallback={fallback}>
      <LazyTreasurerQueueAg {...props} />
    </Suspense>
  );
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
  const agGrid = featureAgGridEnabled();

  const queue = pledges.filter((p) => isQueuedPledge(p.status));
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});
  const milestoneKey = queue.map((pledge) => pledge.milestone_id).join("|");

  useEffect(() => {
    const key = adminKey.trim();
    const ids = [...new Set(milestoneKey.split("|").filter(Boolean))];
    if (!key || !ids.length) {
      setVerdicts({});
      return;
    }
    let cancel = false;
    void (async () => {
      const next: Record<string, string> = {};
      for (const id of ids) {
        try {
          const row = await captainReview(id, key);
          next[id] = String(row.proposal || "");
        } catch {
          next[id] = "";
        }
      }
      if (!cancel) setVerdicts(next);
    })();
    return () => {
      cancel = true;
    };
  }, [adminKey, milestoneKey]);

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

  const gridRows = useMemo(
    () => queue.map((p) => ({ ...p, verdict: verdicts[p.milestone_id] || "" })),
    [queue, verdicts],
  );
  const approveLabel = t("treasurer.approveReview");

  const fallbackTable = (
    <FallbackQueueTable
      queue={queue}
      verdicts={verdicts}
      busyId={busyId}
      approveLabel={approveLabel}
      onApprove={(id, action) => void runAction(id, action)}
    />
  );

  return (
    <section className="panel treasurer-queue">
      <h2>{t("treasurer.heading")}</h2>
      <p className="hint">{t("treasurer.adminKeyHint")}</p>
      <button type="button" onClick={onRefresh} disabled={loading}>
        {t("treasurer.refresh")}
      </button>
      {error ? (
        <p className="notice error">
          {t("treasurer.loadError")}: {error}
        </p>
      ) : null}
      {actionError ? <p className="notice error">{actionError}</p> : null}

      {needsKey ? (
        <p className="hint">{t("treasurer.queueNeedsKey")}</p>
      ) : queue.length === 0 ? (
        <p className="hint">{t("treasurer.queueEmpty")}</p>
      ) : agGrid ? (
        <OptionalAgQueue
          rows={gridRows}
          busyId={busyId}
          approveLabel={approveLabel}
          onApprove={(id, action) => void runAction(id, action)}
          fallback={fallbackTable}
        />
      ) : (
        fallbackTable
      )}
    </section>
  );
}

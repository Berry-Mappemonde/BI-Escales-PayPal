import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  approveCaptainReview,
  captainReview,
  capturePledge,
  refundPledge,
  voidPledge,
} from "../api/escales";
import { isCaptainRateLimitMessage } from "../api/captainRateLimit";
import type { PublicPledge } from "../api/types";
import { isQueuedPledge, isRefundablePledge, isTreasurerQueueRow } from "../hooks/queueFilter";

export interface TreasurerQueueProps {
  pledges: PublicPledge[];
  loading?: boolean;
  error?: string | null;
  needsKey?: boolean;
  adminKey: string;
  demoTreasurer?: boolean;
  onRefresh: () => void;
  onUpdated: (pledge: PublicPledge) => void;
}

export function TreasurerQueue({
  pledges,
  loading,
  error,
  needsKey,
  adminKey,
  demoTreasurer = false,
  onRefresh,
  onUpdated,
}: TreasurerQueueProps) {
  const { t, i18n } = useTranslation();
  const [actionError, setActionError] = useState<string | null>(null);
  const [reviewRateLimit, setReviewRateLimit] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [approvedMilestones, setApprovedMilestones] = useState<Record<string, boolean>>({});

  const queue = pledges.filter((p) => isTreasurerQueueRow(p.status));
  const pending = queue.filter((p) => isQueuedPledge(p.status));
  // Capture, void, refund and review approval always need the treasurer key, even in demo.
  const canMoveMoney = Boolean(adminKey.trim());
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});
  const [toolCalls, setToolCalls] = useState<{ tool: string; resource_id?: string }[]>([]);
  const milestoneKey = pending.map((pledge) => pledge.milestone_id).join("|");

  useEffect(() => {
    const key = adminKey.trim();
    const ids = [...new Set(milestoneKey.split("|").filter(Boolean))];
    if (!demoTreasurer && !key) {
      setVerdicts({});
      return;
    }
    if (!ids.length) {
      setVerdicts({});
      setReviewRateLimit(null);
      return;
    }
    let cancel = false;
    setReviewRateLimit(null);
    void (async () => {
      const next: Record<string, string> = {};
      for (const id of ids) {
        try {
          const appLang = i18n.language === "fr" ? "fr" : "en";
          const row = await captainReview(
            id,
            demoTreasurer ? undefined : key,
            appLang,
            demoTreasurer ? { demoTreasurer: true } : undefined,
          );
          next[id] = String(row.proposal || "");
          if (row.paypal_tool_calls?.length) {
            setToolCalls(row.paypal_tool_calls);
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (isCaptainRateLimitMessage(message)) {
            setReviewRateLimit(t("escales.rateLimit"));
          }
          next[id] = "";
        }
      }
      if (!cancel) setVerdicts(next);
    })();
    return () => {
      cancel = true;
    };
  }, [adminKey, demoTreasurer, milestoneKey, i18n.language, t]);

  const runAction = async (pledgeId: string, action: "capture" | "void" | "refund") => {
    if (!canMoveMoney) {
      setActionError(t("treasurer.moneyNeedsKey"));
      return;
    }
    setBusyId(pledgeId);
    setActionError(null);
    try {
      const updated =
        action === "capture"
          ? await capturePledge(pledgeId, adminKey.trim(), undefined)
          : action === "refund"
            ? await refundPledge(pledgeId, adminKey.trim(), undefined, undefined)
            : await voidPledge(pledgeId, adminKey.trim(), undefined);
      onUpdated(updated);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const approveReview = async (milestoneId: string) => {
    if (!canMoveMoney) {
      setActionError(t("treasurer.moneyNeedsKey"));
      return;
    }
    setActionError(null);
    try {
      await approveCaptainReview(milestoneId, adminKey.trim(), undefined);
      setApprovedMilestones((prev) => ({ ...prev, [milestoneId]: true }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="panel treasurer-queue">
      <h2>{t("treasurer.heading")}</h2>
      <button type="button" onClick={onRefresh} disabled={loading}>
        {t("treasurer.refresh")}
      </button>
      {error ? <p className="notice error">{t("treasurer.loadError")}: {error}</p> : null}
      {toolCalls.length ? (
        <ul className="tool-call-log" data-testid="paypal-tool-calls">
          {toolCalls.map((row, index) => (
            <li key={`${row.tool}-${index}`}>
              {row.tool}
              {row.resource_id ? ` — ${row.resource_id}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {actionError ? <p className="notice error">{actionError}</p> : null}
      {reviewRateLimit ? (
        <p className="notice warn" data-testid="captain-review-rate-limit">
          {reviewRateLimit}
        </p>
      ) : null}

      {demoTreasurer && !canMoveMoney && queue.length ? (
        <p className="hint" data-testid="treasurer-demo-readonly">
          {t("treasurer.moneyNeedsKey")}
        </p>
      ) : null}
      {needsKey ? (
        <p className="hint">{t("treasurer.queueNeedsKey")}</p>
      ) : queue.length === 0 ? (
        <p className="hint">{t("treasurer.queueEmpty")}</p>
      ) : (
        <table className="fallback-table">
          <thead>
            <tr>
              <th>{t("treasurer.status")}</th>
              <th>{t("treasurer.captureId")}</th>
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
                <td data-testid={`capture-id-${p.id}`}>{p.capture_id || "—"}</td>
                <td>
                  {p.amount_eur} {p.currency}
                </td>
                <td>{p.description}</td>
                <td>{p.milestone_id}</td>
                <td data-testid={`verdict-${p.id}`}>{verdicts[p.milestone_id] || ""}</td>
                <td className="actions">
                  {isQueuedPledge(p.status) ? (
                    <>
                      <button
                        type="button"
                        data-testid={`approve-${p.id}`}
                        disabled={!canMoveMoney || busyId === p.id || approvedMilestones[p.milestone_id]}
                        onClick={() => void approveReview(p.milestone_id)}
                      >
                        {t("treasurer.approveReview")}
                      </button>
                      {verdicts[p.milestone_id] === "capture" ? (
                        <button
                          type="button"
                          data-testid={`capture-${p.id}`}
                          disabled={!canMoveMoney || busyId === p.id || !approvedMilestones[p.milestone_id]}
                          onClick={() => void runAction(p.id, "capture")}
                        >
                          {t("treasurer.capturePledge")}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        data-testid={`void-${p.id}`}
                        disabled={!canMoveMoney || busyId === p.id}
                        onClick={() => void runAction(p.id, "void")}
                      >
                        {t("treasurer.notSailingVoid")}
                      </button>
                    </>
                  ) : null}
                  {isRefundablePledge(p.status) ? (
                    <button
                      type="button"
                      data-testid={`refund-${p.id}`}
                      disabled={!canMoveMoney || busyId === p.id}
                      onClick={() => void runAction(p.id, "refund")}
                    >
                      {t("treasurer.refundPledge")}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

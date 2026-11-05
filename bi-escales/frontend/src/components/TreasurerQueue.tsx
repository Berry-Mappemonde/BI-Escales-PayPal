import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  approveCaptainReview,
  captainReview,
  capturePledge,
  fetchSchedule,
  refundPledge,
} from "../api/escales";
import { isCaptainRateLimitMessage } from "../api/captainRateLimit";
import type { CaptainProposal, PublicPledge, ScheduleResponse } from "../api/types";
import { isQueuedPledge, isRefundablePledge, isTreasurerQueueRow } from "../hooks/queueFilter";
import { CaptainReviewCard } from "./captain/CaptainReviewCard";
import { releasableHolds, stopOnSchedule } from "./captain/captainEvidence";
import { PledgeStatusChip } from "./captain/PledgeStatusChip";
import { useHoldRelease } from "./captain/useHoldRelease";

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
  /** A missing key means the review is still loading; null means it failed. */
  const [reviews, setReviews] = useState<Record<string, CaptainProposal | null>>({});
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const { releases, start: startRelease, undo: undoRelease } = useHoldRelease({
    adminKey,
    missingKeyMessage: t("treasurer.moneyNeedsKey"),
    onUpdated,
  });
  // One entry per milestone, so voiding one of several holds does not re-run the rate-limited review.
  const milestoneKey = [...new Set(pending.map((pledge) => pledge.milestone_id))].sort().join("|");
  // A milestone keeps its card after its last hold is released, so the result stays visible.
  const cardIds = [...new Set([...milestoneKey.split("|").filter(Boolean), ...Object.keys(releases)])];

  useEffect(() => {
    const key = adminKey.trim();
    const ids = [...new Set(milestoneKey.split("|").filter(Boolean))];
    if (!demoTreasurer && !key) {
      setReviews({});
      return;
    }
    if (!ids.length) {
      setReviewRateLimit(null);
      return;
    }
    let cancel = false;
    setReviewRateLimit(null);
    void (async () => {
      for (const id of ids) {
        if (cancel) return;
        try {
          const appLang = i18n.language === "fr" ? "fr" : "en";
          const row = await captainReview(
            id,
            demoTreasurer ? undefined : key,
            appLang,
            demoTreasurer ? { demoTreasurer: true } : undefined,
          );
          if (!cancel) setReviews((all) => ({ ...all, [id]: row }));
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (isCaptainRateLimitMessage(message)) {
            setReviewRateLimit(t("escales.rateLimit"));
          }
          if (!cancel) setReviews((all) => ({ ...all, [id]: null }));
        }
      }
    })();
    return () => {
      cancel = true;
    };
  }, [adminKey, demoTreasurer, milestoneKey, i18n.language, t]);

  const needsSchedule = Boolean(milestoneKey) && !schedule;
  useEffect(() => {
    if (!needsSchedule) return;
    let cancel = false;
    // The arrival claim is optional: without a schedule the card simply omits it.
    fetchSchedule()
      .then((row) => {
        if (!cancel) setSchedule(row);
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [needsSchedule]);

  const runAction = async (pledgeId: string, action: "capture" | "refund") => {
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
          : await refundPledge(pledgeId, adminKey.trim(), undefined, undefined);
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

  // A pledge inside an undo window must not be captured out from under the release.
  const releaseRunning = (milestoneId: string) => {
    const phase = releases[milestoneId]?.phase;
    return phase === "counting" || phase === "sending";
  };

  return (
    <section className="panel treasurer-queue">
      <h2>{t("treasurer.heading")}</h2>
      <button type="button" onClick={onRefresh} disabled={loading}>
        {t("treasurer.refresh")}
      </button>
      {error ? <p className="notice error">{t("treasurer.loadError")}: {error}</p> : null}
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
      {!needsKey && cardIds.length ? (
        <div className="captain-cards">
          {cardIds.map((milestoneId) => {
            const stop = stopOnSchedule(schedule, milestoneId);
            return (
              <CaptainReviewCard
                key={milestoneId}
                milestoneId={milestoneId}
                stopName={stop.name}
                arrivalIso={stop.arrivalIso}
                review={reviews[milestoneId]}
                holds={releasableHolds(pledges, milestoneId)}
                canMoveMoney={canMoveMoney}
                approved={Boolean(approvedMilestones[milestoneId])}
                release={releases[milestoneId]}
                onApprove={() => void approveReview(milestoneId)}
                onRelease={(holds) => startRelease(milestoneId, holds)}
                onUndo={() => undoRelease(milestoneId)}
              />
            );
          })}
        </div>
      ) : null}
      {needsKey ? (
        <p className="hint">{t("treasurer.queueNeedsKey")}</p>
      ) : queue.length === 0 ? (
        <p className="hint">{t("treasurer.queueEmpty")}</p>
      ) : (
        <div className="treasurer-queue-table">
        <table className="fallback-table">
          <thead>
            <tr>
              <th>{t("treasurer.status")}</th>
              <th>{t("treasurer.captureId")}</th>
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
                  <PledgeStatusChip status={p.status} />
                </td>
                <td data-testid={`capture-id-${p.id}`}>{p.capture_id || "—"}</td>
                <td>
                  {p.amount_eur} {p.currency}
                </td>
                <td>{p.description}</td>
                <td>{p.milestone_id}</td>
                <td className="actions">
                  {isQueuedPledge(p.status) && reviews[p.milestone_id]?.proposal === "capture" ? (
                    <button
                      type="button"
                      data-testid={`capture-${p.id}`}
                      disabled={
                        !canMoveMoney ||
                        busyId === p.id ||
                        !approvedMilestones[p.milestone_id] ||
                        releaseRunning(p.milestone_id)
                      }
                      onClick={() => void runAction(p.id, "capture")}
                    >
                      {t("treasurer.capturePledge")}
                    </button>
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
        </div>
      )}
    </section>
  );
}

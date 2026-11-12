import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CaptainProposal, PublicPledge } from "../../api/types";
import {
  buildEvidence,
  sumEur,
  type CaptainClaim,
  type CaptainSource,
} from "./captainEvidence";
import { formatAdvisoryReason } from "./formatAdvisoryReason";
import { CaptainToolTrace } from "./CaptainToolTrace";
import { PledgeStatusChip } from "./PledgeStatusChip";
import { useFocusFirstButton } from "./useFocusFirstButton";
import { UNDO_WINDOW_SECONDS, type HoldRelease } from "./useHoldRelease";
import "./captain-card.css";

export interface CaptainReviewCardProps {
  milestoneId: string;
  stopName?: string;
  /** Fallback ETA, used only when the review does not carry the one it read. */
  arrivalIso?: string;
  /** null once the review failed, undefined while it loads. */
  review: CaptainProposal | null | undefined;
  /** Holds Override would release, from the live queue. */
  holds: PublicPledge[];
  canMoveMoney: boolean;
  approved: boolean;
  release?: HoldRelease;
  onApprove: () => void;
  onRelease: (holds: PublicPledge[]) => void;
  onUndo: () => void;
}

const PROPOSALS = new Set(["capture", "void", "wait", "reauthorize"]);

function useFormatters(language: string) {
  return useMemo(() => {
    const locale = language === "fr" ? "fr-FR" : "en-GB";
    const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" });
    const money = (amount: number) =>
      new Intl.NumberFormat(locale, {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
        maximumFractionDigits: 2,
      }).format(amount);
    return { day: (iso: string) => day.format(new Date(iso)), money };
  }, [language]);
}

export function CaptainReviewCard({
  milestoneId,
  stopName,
  arrivalIso,
  review,
  holds,
  canMoveMoney,
  approved,
  release,
  onApprove,
  onRelease,
  onUndo,
}: CaptainReviewCardProps) {
  const { t, i18n } = useTranslation();
  const format = useFormatters(i18n.language);
  const [confirming, setConfirming] = useState(false);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const sourceRefs = useRef(new Map<number, HTMLLIElement>());

  const phase = release?.phase;
  const decisionRef = useFocusFirstButton<HTMLElement>(`${phase}:${confirming}:${approved}`);
  const { claims, sources } = buildEvidence(review ?? null, arrivalIso);

  const total = format.money(sumEur(holds.map((pledge) => pledge.amount_eur)));

  useEffect(() => {
    if (phase) setConfirming(false);
  }, [phase]);

  const sourceName = (source: CaptainSource) =>
    source.kind === "schedule"
      ? t("captainCard.sourceSchedule")
      : source.kind === "logbook"
        ? t("captainCard.sourceLogbook")
        : source.kind;

  const claimText = (claim: CaptainClaim) => {
    switch (claim.key) {
      case "arrival":
        return t("captainCard.claimArrival", { date: format.day(claim.iso ?? "") });
      case "logbook": {
        const label = (i18n.language === "fr" ? claim.entry?.label_fr : claim.entry?.label_en) || "";
        return t("captainCard.claimLogbook", { date: format.day(claim.iso ?? ""), entry: label });
      }
      case "logbookEmpty":
        return t("captainCard.claimLogbookEmpty");
      case "holds":
        return t("captainCard.claimHolds", { count: claim.count, total: format.money(claim.totalEur ?? 0) });
      case "validTo":
        return t("captainCard.claimValidTo", { date: format.day(claim.iso ?? "") });
      case "expired":
        return t("captainCard.claimExpired", { date: format.day(claim.iso ?? "") });
      case "authorizationsRead":
        return t("captainCard.claimAuthorizationsRead", { count: claim.count });
      case "ordersRead":
        return t("captainCard.claimOrdersRead", { count: claim.count });
    }
  };

  const showSource = (n: number) => {
    setActiveCite(n);
    sourceRefs.current.get(n)?.focus();
  };

  const proposal = String(review?.proposal ?? "");
  const proposalLabel = PROPOSALS.has(proposal)
    ? t(`captainCard.proposal.${proposal}`)
    : proposal || t("captainCard.proposal.none");
  // report is justification without its closing "Decision: …" line, which the heading already gives.
  const report = review?.report || review?.justification;
  const advisory = formatAdvisoryReason(review?.llm_proposal?.reason, i18n.language, t);

  const captureRule = t("captainCard.rule");
  const showCaptureRule = holds.length > 0 && !report?.includes(captureRule) && !advisory?.includes(captureRule);

  // Failed voids stay in the queue, so the live holds are always what a retry would release.
  const showChoice = !phase || phase === "cancelled" || (phase === "done" && holds.length > 0);
  const counting = phase === "counting";

  return (
    <article className="captain-card" data-testid={`captain-card-${milestoneId}`}>
      <header className="captain-card-head">
        <h3>{t("captainCard.heading")}</h3>
        {/* The stop's name; the raw id stays one hover away, as in the queue below. */}
        <p className="captain-meta" data-testid={`captain-stop-${milestoneId}`} title={milestoneId}>
          {stopName || milestoneId}
        </p>
      </header>

      {review === undefined ? (
        <section className="captain-section">
          <p className="captain-meta rail-loading" role="status">
            {t("captainCard.reviewing")}
          </p>
        </section>
      ) : null}

      {review === null ? (
        <section className="captain-section">
          <p className="captain-read">{t("captainCard.unavailable")}</p>
        </section>
      ) : null}

      {review ? (
        <section className="captain-section">
          <p className="captain-label">{t("captainCard.proposalLabel")}</p>
          <p className="captain-proposal" data-testid={`captain-proposal-${milestoneId}`}>
            {proposalLabel}
          </p>
          {report ? <p className="captain-read">{report}</p> : null}
          {advisory ? (
            <p className="captain-advisory">
              <span className="captain-label">{t("captainCard.advisory")}</span> {advisory}
            </p>
          ) : null}
        </section>
      ) : null}

      {claims.length ? (
        <section className="captain-section" data-testid={`captain-basis-${milestoneId}`}>
          <p className="captain-label">{t("captainCard.basis")}</p>
          <ul className="captain-claims">
            {claims.map((claim) => {
              const source = sources[claim.cite - 1];
              return (
                <li key={claim.key}>
                  <span className="captain-claim-text">
                    {claimText(claim)}{" "}
                    <button
                      type="button"
                      className="captain-cite"
                      aria-label={t("captainCard.citeLabel", { n: claim.cite, source: sourceName(source) })}
                      onClick={() => showSource(claim.cite)}
                    >
                      {claim.cite}
                    </button>
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="captain-label captain-sources-title">{t("captainCard.sources")}</p>
          <ol className="captain-sources">
            {sources.map((source) => (
              <li
                key={source.n}
                ref={(el) => {
                  if (el) sourceRefs.current.set(source.n, el);
                  else sourceRefs.current.delete(source.n);
                }}
                tabIndex={-1}
                data-active={activeCite === source.n || undefined}
                onBlur={() => setActiveCite(null)}
              >
                <span className="captain-cite-num" aria-hidden="true">
                  {source.n}
                </span>
                <span className={source.kind === "schedule" || source.kind === "logbook" ? undefined : "captain-mono"}>{sourceName(source)}</span>
                {source.ids.length ? <span className="captain-mono captain-ids">{source.ids.join(", ")}</span> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section
        ref={decisionRef}
        className="captain-section captain-decision"
        aria-label={t("captainCard.decision")}
        tabIndex={-1}
      >
        {counting ? (
          <div className="captain-countdown" data-testid={`captain-countdown-${milestoneId}`}>
            {/* Hidden from screen readers so they hear one announcement, not one per second. */}
            <span aria-hidden="true">{t("captainCard.releasing", { seconds: release?.secondsLeft })}</span>
            <span aria-hidden="true" className="captain-dot">
              ·
            </span>
            <button type="button" className="captain-undo" onClick={onUndo}>
              {t("captainCard.undo")}
            </button>
          </div>
        ) : null}

        <p className={counting ? "captain-sr-only" : "captain-ui"} role="status">
          {counting ? t("captainCard.releasingAnnounce", { seconds: UNDO_WINDOW_SECONDS }) : null}
          {phase === "sending" ? t("captainCard.sending") : null}
          {phase === "cancelled" ? t("captainCard.cancelled") : null}
          {phase === "done" && release?.releasedCount
            ? t("captainCard.released", { count: release.releasedCount, total: format.money(release.releasedEur) })
            : null}
        </p>

        {phase === "done" && release?.releasedCount ? <PledgeStatusChip status="voided" /> : null}

        {phase === "done" && release?.failed.length ? (
          <div className="captain-failed" role="alert">
            <p>{t("captainCard.failed", { count: release.failed.length })}</p>
            <ul>
              {release.failed.map((row) => (
                <li key={row.pledge.id}>
                  <span className="captain-mono">{row.pledge.id}</span> {row.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {showChoice && confirming ? (
          <div role="group" aria-labelledby={`void-question-${milestoneId}`}>
            <p className="captain-ui" id={`void-question-${milestoneId}`}>
              {t("captainCard.voidConfirmation", { count: holds.length, total })}
            </p>
            <div className="captain-actions">
              <button
                type="button"
                className="secondary"
                data-testid={`captain-release-${milestoneId}`}
                disabled={!canMoveMoney || !holds.length}
                onClick={() => onRelease(holds)}
              >
                {t("treasurer.confirm")}
              </button>
              <button type="button" className="captain-ghost" onClick={() => setConfirming(false)}>
                {t("captainCard.cancel")}
              </button>
            </div>
          </div>
        ) : null}

        {showChoice && !confirming ? (
          <div className="captain-actions">
            {phase !== "done" ? (
              <button
                type="button"
                className="captain-primary"
                data-testid={`captain-approve-${milestoneId}`}
                disabled={!canMoveMoney || !review || approved}
                onClick={onApprove}
              >
                {approved ? t("captainCard.approved") : t("captainCard.approve")}
              </button>
            ) : null}
            {holds.length ? (
              <button
                type="button"
                className="secondary"
                data-testid={`captain-override-${milestoneId}`}
                disabled={!canMoveMoney}
                onClick={() => setConfirming(true)}
              >
                {release?.failed.length ? t("captainCard.retry") : t("captainCard.override")}
              </button>
            ) : null}
          </div>
        ) : null}

        {showCaptureRule ? <p className="captain-meta">{captureRule}</p> : null}
      </section>

      {review ? (
        <footer className="captain-answered" data-testid={`captain-answered-${milestoneId}`}>
          <CaptainToolTrace trace={review} />
        </footer>
      ) : null}
    </article>
  );
}

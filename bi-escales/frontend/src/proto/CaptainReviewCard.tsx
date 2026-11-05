import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDay, type Lang } from "./format";
import { review, stop } from "./mock";
import { useFocusFirstButton } from "./useFocusFirstButton";

type Decision = "pending" | "choosing" | "approved" | "capture" | "release";

const RESULT_KEY: Partial<Record<Decision, string>> = {
  approved: "captain.resultApproved",
  capture: "captain.resultCapture",
  release: "captain.resultRelease",
};

export function CaptainReviewCard({ lang }: { lang: Lang }) {
  const { t } = useTranslation();
  const [decision, setDecision] = useState<Decision>("pending");
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const sourceRefs = useRef(new Map<number, HTMLLIElement>());
  const decisionRef = useFocusFirstButton<HTMLElement>(decision);

  const eta = formatDay(stop.arrivalEta, lang);
  const validTo = formatDay(review.authorizationValidTo, lang);
  const resultKey = RESULT_KEY[decision];

  const sources = [
    { n: 1, name: t("captain.logbook"), detail: t("captain.logbookDetail", { date: eta }) },
    {
      n: 2,
      name: "authorizations.get",
      tool: true,
      id: review.authorizationId,
      detail: t("captain.validTo", { date: validTo }),
    },
    { n: 3, name: "orders.get", tool: true, detail: t("captain.approved") },
  ];

  function showSource(n: number) {
    setActiveCite(n);
    sourceRefs.current.get(n)?.focus();
  }

  // Each badge stays on one line with the word before it, so it never starts a line alone.
  const rationale = t("captain.rationale", { eta, validTo })
    .split(/(\S+ \[\d\])/)
    .map((part, index) => {
      const match = /^(\S+) \[(\d)\]$/.exec(part);
      if (!match) return part;
      const n = Number(match[2]);
      const source = sources[n - 1].name;
      return (
        <span key={index} className="proto-claim-end">
          {match[1]}{" "}
          <button
            type="button"
            className="proto-cite"
            aria-label={t("captain.citeLabel", { n, source })}
            onClick={() => showSource(n)}
          >
            {n}
          </button>
        </span>
      );
    });

  return (
    <article className="proto-card proto-captain" aria-labelledby="proto-captain-title">
      <header className="proto-card-head">
        <h1 id="proto-captain-title" className="proto-card-title">
          {t("captain.title")}
        </h1>
        <p className="proto-meta">
          {t("captain.subject", { stop: stop.name, from: stop.from, to: stop.name })}
        </p>
      </header>

      <section className="proto-section" aria-labelledby="proto-proposal-title">
        <h2 id="proto-proposal-title" className="proto-section-title">
          {t("captain.proposalLabel")}
        </h2>
        <p className="proto-heading">{t("captain.proposal")}</p>
        <p className="proto-read">{rationale}</p>
      </section>

      <section className="proto-section" aria-labelledby="proto-sources-title">
        <h2 id="proto-sources-title" className="proto-section-title">
          {t("captain.sources")}
        </h2>
        <ol className="proto-sources">
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
              <span className="proto-cite-num" aria-hidden="true">
                {source.n}
              </span>
              <span className={source.tool ? "proto-mono" : undefined}>{source.name}</span>
              <span className="proto-source-detail">
                {source.id ? <span className="proto-mono">{source.id}</span> : null}
                {source.detail}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section ref={decisionRef} className="proto-section proto-decision" aria-label={t("captain.title")}>
        {decision === "pending" ? (
          <div className="proto-actions">
            <button type="button" className="proto-btn" data-variant="primary" onClick={() => setDecision("approved")}>
              {t("captain.approve")}
            </button>
            <button type="button" className="proto-btn" onClick={() => setDecision("choosing")}>
              {t("captain.override")}
            </button>
          </div>
        ) : null}

        {decision === "choosing" ? (
          <>
            <p className="proto-ui">{t("captain.overrideTitle")}</p>
            <div className="proto-actions">
              <button type="button" className="proto-btn" onClick={() => setDecision("capture")}>
                {t("captain.captureNow")}
              </button>
              <button type="button" className="proto-btn" onClick={() => setDecision("release")}>
                {t("captain.releaseHold")}
              </button>
              <button type="button" className="proto-btn" data-variant="ghost" onClick={() => setDecision("pending")}>
                {t("captain.cancel")}
              </button>
            </div>
          </>
        ) : null}

        <p className="proto-ui" role="status">
          {resultKey ? t(resultKey) : ""}
        </p>

        {resultKey ? (
          <div className="proto-actions">
            <button type="button" className="proto-btn" data-variant="ghost" onClick={() => setDecision("pending")}>
              {t("captain.undo")}
            </button>
          </div>
        ) : (
          <p className="proto-meta">{t("captain.humanRule")}</p>
        )}
      </section>
    </article>
  );
}

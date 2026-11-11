import { useTranslation } from "react-i18next";
import "./stop-panel.css";

const STEPS = [
  { key: "authorize", tone: "held" },
  { key: "arrivalApproval" },
  { key: "captured", tone: "captured" },
];

/**
 * What the right panel shows until a stop is picked. The one primary action is
 * backing the next stop; the map stays the way to pick any other.
 */
export function HowItWorks({ nextStopName, onBackNextStop, nextStopPending = false }) {
  const { t } = useTranslation();
  return (
    <section className="how-it-works" data-testid="how-it-works">
      <p className="how-it-works-eyebrow">{t("howItWorks.eyebrow")}</p>
      <h2>{t("howItWorks.heading")}</h2>
      <p className="how-it-works-intro">{t("howItWorks.intro")}</p>
      {nextStopName && onBackNextStop ? (
        <button
          type="button"
          className="how-it-works-cta"
          data-testid="back-next-stop"
          aria-label={t("howItWorks.backNextNamed", { name: nextStopName })}
          onClick={onBackNextStop}
        >
          <span>{t("howItWorks.backNext")}</span>
          <span className="how-it-works-cta-stop">{nextStopName}</span>
        </button>
      ) : nextStopPending ? (
        // Same button, same size, not yet usable: the next stop is named only once
        // the schedule has answered, so the label never changes under the pointer.
        <button
          type="button"
          className="how-it-works-cta"
          data-testid="back-next-stop-pending"
          aria-busy="true"
          disabled
        >
          <span>{t("howItWorks.backNext")}</span>
          <span className="how-it-works-cta-stop">{t("howItWorks.backNextLoading")}</span>
        </button>
      ) : null}
      <p className="how-it-works-pick">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M19 10.2c0 5.2-7 11-7 11s-7-5.8-7-11a7 7 0 1 1 14 0Z" stroke="currentColor" strokeWidth="1.7" />
          <circle cx="12" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.7" />
        </svg>
        <span>{t("howItWorks.pick")}</span>
      </p>
      <ol className="how-steps">
        {STEPS.map(({ key, tone }) => (
          <li key={key} data-tone={tone}>
            <strong>{t(`howItWorks.${key}`)}</strong>
            <span>{t(`howItWorks.${key}Detail`)}</span>
          </li>
        ))}
      </ol>
      <div className="how-it-works-notes">
        <p>{t("howItWorks.cancelled")}</p>
        <p>{t("howItWorks.cabin")}</p>
      </div>
      <footer className="how-it-works-credit">{t("howItWorks.credit")}</footer>
    </section>
  );
}

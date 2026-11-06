import { useTranslation } from "react-i18next";
import "./stop-panel.css";

const STEPS = [
  { key: "authorize", tone: "held" },
  { key: "arrivalApproval" },
  { key: "captured", tone: "captured" },
];

/** What the right panel shows until a stop is picked. Static, no data. */
export function HowItWorks() {
  const { t } = useTranslation();
  return (
    <section className="how-it-works" data-testid="how-it-works">
      <p className="how-it-works-eyebrow">{t("howItWorks.eyebrow")}</p>
      <h2>{t("howItWorks.heading")}</h2>
      <p className="how-it-works-intro">{t("howItWorks.intro")}</p>
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
      <p className="how-it-works-pick">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M19 10.2c0 5.2-7 11-7 11s-7-5.8-7-11a7 7 0 1 1 14 0Z" stroke="currentColor" strokeWidth="1.7" />
          <circle cx="12" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.7" />
        </svg>
        <span>{t("howItWorks.pick")}</span>
      </p>
    </section>
  );
}

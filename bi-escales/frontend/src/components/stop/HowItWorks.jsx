import { useTranslation } from "react-i18next";
import "./stop-panel.css";

const STEPS = [
  { key: "pledge" },
  { key: "held", tone: "held" },
  { key: "arrives", tone: "route" },
  { key: "approves" },
  { key: "captured", tone: "captured" },
  { key: "released", tone: "released" },
];

/** What the right panel shows until a stop is picked. Static, no data. */
export function HowItWorks() {
  const { t } = useTranslation();
  return (
    <section className="how-it-works" data-testid="how-it-works">
      <h2>{t("howItWorks.heading")}</h2>
      <ol className="how-steps">
        {STEPS.map(({ key, tone }) => (
          <li key={key} data-tone={tone}>
            <strong>{t(`howItWorks.${key}`)}</strong>
            <span>{t(`howItWorks.${key}Detail`)}</span>
          </li>
        ))}
      </ol>
      <p className="how-it-works-pick">{t("sheet.pick")}</p>
    </section>
  );
}

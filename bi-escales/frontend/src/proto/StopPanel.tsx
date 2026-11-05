import { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDay, formatDayTime, formatEur, type Lang } from "./format";
import { stop } from "./mock";
import { StatusChip, StatusGlyph } from "./StatusChip";
import { useFocusFirstButton } from "./useFocusFirstButton";

export function StopPanel({ lang }: { lang: Lang }) {
  const { t } = useTranslation();
  const [backed, setBacked] = useState(false);
  const nextStepRef = useFocusFirstButton<HTMLElement>(backed);
  const eta = formatDay(stop.arrivalEta, lang);

  return (
    <article className="proto-card proto-stop" aria-labelledby="proto-stop-title">
      <header className="proto-card-head">
        <div className="proto-title-row">
          <h1 id="proto-stop-title" className="proto-heading">
            {stop.name}
          </h1>
          <StatusChip status="en_route" />
        </div>
        <p className="proto-meta">
          {t("stop.region")} · {t("stop.leg", { from: stop.from, to: stop.name })}
        </p>
      </header>

      <section className="proto-section" aria-label={t("stop.details")}>
        <dl className="proto-props">
          <div>
            <dt>{t("stop.arrival")}</dt>
            <dd>{t("stop.arrivalValue", { date: eta })}</dd>
          </div>
          <div>
            <dt>{t("stop.departure")}</dt>
            <dd>{t("stop.departureValue", { date: formatDay(stop.departurePlanned, lang) })}</dd>
          </div>
          <div>
            <dt>{t("stop.marina")}</dt>
            <dd>{stop.marina}</dd>
          </div>
        </dl>
      </section>

      <section className="proto-section" aria-labelledby="proto-logbook-title">
        <h2 id="proto-logbook-title" className="proto-section-title">
          {t("stop.logbook")}
        </h2>
        <ol className="proto-log">
          {stop.logbook.map((entry) => (
            <li key={entry.key}>
              <span className="proto-log-text">{t(`stop.log.${entry.key}`, { date: eta })}</span>
              <time className="proto-log-time" dateTime={entry.at}>
                {formatDayTime(entry.at, lang)}
              </time>
            </li>
          ))}
        </ol>
      </section>

      <section ref={nextStepRef} className="proto-section proto-next" aria-labelledby="proto-next-title">
        <div className="proto-next-head">
          <h2 id="proto-next-title" className="proto-next-title">
            {backed ? <StatusGlyph status="held" /> : null}
            {backed ? t("stop.backing") : t("stop.nextStep")}
          </h2>
          <span className="proto-amount">{formatEur(stop.pledgeEur, lang)}</span>
        </div>
        <p className="proto-held">{t("stop.held")}</p>
        <p className="proto-meta">{t("stop.rule", { stop: stop.name })}</p>
        <div className="proto-actions">
          {backed ? (
            <button key="undo" type="button" className="proto-btn" data-variant="ghost" onClick={() => setBacked(false)}>
              {t("stop.undo")}
            </button>
          ) : (
            <button key="back" type="button" className="proto-btn" data-variant="primary" onClick={() => setBacked(true)}>
              {t("stop.back")}
            </button>
          )}
          <p className="proto-meta" role="status">
            {backed ? t("stop.backedNote") : ""}
          </p>
        </div>
      </section>
    </article>
  );
}

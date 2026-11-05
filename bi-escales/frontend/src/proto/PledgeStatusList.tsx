import { useTranslation } from "react-i18next";
import { pledgeStates } from "./mock";
import { StatusChip } from "./StatusChip";

export function PledgeStatusList({ hidden }: { hidden: boolean }) {
  const { t } = useTranslation();

  return (
    <article className="proto-card proto-pledges" aria-labelledby="proto-pledges-title" hidden={hidden}>
      <header className="proto-card-head">
        <h1 id="proto-pledges-title" className="proto-card-title">
          {t("pledges.title")}
        </h1>
        <p className="proto-meta">{t("pledges.intro")}</p>
      </header>
      <ul className="proto-states">
        {pledgeStates.map((state) => (
          <li key={state.id} data-testid={`pledge-${state.id}`}>
            <StatusChip status={state.id} />
            <span className="proto-state-meaning">{t(`pledges.meaning.${state.id}`)}</span>
            <code className="proto-mono proto-state-backend" aria-label={`${t("pledges.backendLabel")}: ${state.backend}`}>
              {state.backend}
            </code>
          </li>
        ))}
      </ul>
    </article>
  );
}

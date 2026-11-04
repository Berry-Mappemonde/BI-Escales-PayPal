/**
 * Liste des projets. Copie adaptée de
 * Blue-Intelligence frontend/src/components/ProjectList.js
 * (filtre via filterProjectFeatures.js ; promesse Escales).
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { filterProjectFeatures } from "../projects/filterProjectFeatures.js";
import { PledgeButton } from "./PledgeButton";

/** Même plafond que ProjectList.js BI (slice 0, 100). */
const LIST_CAP = 100;
const MIN_EUR = "1.00";

function ProjectPledgeForm({ project, contributor, onAuthorized }) {
  const { t } = useTranslation();
  const props = project?.properties || {};
  const [amount, setAmount] = useState(MIN_EUR);
  const [who, setWho] = useState(contributor || "");
  const title = props.title || props.id || "";
  const description = t("projects.pledgeDescription", { title });
  const tooLow = Number(amount) > 0 && Number(amount) < 1;

  return (
    <div className="project-pledge" data-testid="project-pledge" data-project-id={props.id}>
      <label>
        {t("pledge.amount")}
        <input
          data-testid="project-pledge-amount"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </label>
      <label>
        {t("pledge.contributor")}
        <input
          data-testid="project-pledge-contributor"
          value={who}
          onChange={(event) => setWho(event.target.value)}
        />
      </label>
      {tooLow ? <p className="notice warn">{t("projects.minAmount")}</p> : null}
      <PledgeButton
        values={{
          amount_eur: amount,
          description,
          milestone_id: "",
          contributor: who.trim() || undefined,
          kind: "project_pledge",
          target_id: props.id,
        }}
        disabled={tooLow || Number(amount) < 1}
        onAuthorized={onAuthorized}
      />
    </div>
  );
}

export default function ProjectList({
  projects,
  searchQuery: searchQueryProp = undefined,
  onSearchQueryChange = undefined,
  selectedProjectId,
  onSelectProject,
  contributor = "",
  onFlyTo,
  onAuthorized,
}) {
  const { t } = useTranslation();
  const [localQuery, setLocalQuery] = useState("");
  const query = searchQueryProp ?? localQuery;
  const setQuery = onSearchQueryChange ?? setLocalQuery;

  const filtered = useMemo(
    () => filterProjectFeatures(projects?.features || [], {
      funderFilter: "All",
      categoryFilter: "All",
      searchQuery: query,
    }),
    [projects, query],
  );

  const features = filtered.slice(0, LIST_CAP);
  const truncated = filtered.length > LIST_CAP;

  return (
    <section className="panel" data-testid="project-list">
      <div className="escale-sheet-head">
        <h2>{t("projects.heading")}</h2>
        <span data-testid="project-list-count">{filtered.length}</span>
      </div>
      <input
        data-testid="projects-search-input"
        type="text"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("projects.search")}
        aria-label={t("projects.search")}
      />
      {truncated ? (
        <p className="hint" data-testid="projects-list-truncated">
          {t("projects.truncated", { shown: LIST_CAP, total: filtered.length })}
        </p>
      ) : null}
      {features.length === 0 ? <p className="hint">{t("projects.empty")}</p> : null}
      <div>
        {features.map((feature) => {
          const props = feature.properties || {};
          const open = selectedProjectId === props.id;
          return (
            <div key={props.id} className="project-row" data-testid={`project-row-${props.id}`}>
              <button
                type="button"
                data-testid={`project-item-${props.id}`}
                onClick={() => {
                  const [lon, lat] = feature.geometry?.coordinates || [];
                  if (onFlyTo && lat != null && lon != null) onFlyTo(props.id, lat, lon);
                }}
              >
                <strong>{props.title}</strong>
                <span className="hint">{props.funder}</span>
              </button>
              <button
                type="button"
                data-testid={`project-pledge-open-${props.id}`}
                onClick={() => onSelectProject?.(props.id)}
              >
                {t("projects.pledge")}
              </button>
              {props.url ? (
                <a href={props.url} target="_blank" rel="noreferrer">
                  {t("projects.open")}
                </a>
              ) : null}
              {open ? (
                <ProjectPledgeForm
                  project={feature}
                  contributor={contributor}
                  onAuthorized={onAuthorized}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export { ProjectPledgeForm, LIST_CAP };

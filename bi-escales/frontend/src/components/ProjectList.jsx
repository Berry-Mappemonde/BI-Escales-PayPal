/**
 * Liste des projets. Copie adaptée de
 * Blue-Intelligence frontend/src/components/ProjectList.js
 * (filtre via filterProjectFeatures.js ; promesse Escales).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchPublicProjectFund } from "../api/escales";
import { filterProjectFeatures } from "../projects/filterProjectFeatures.js";
import { parseProjectPledgeAmount } from "../projects/projectPledgeAmount.js";
import { visibleProjectFeatures } from "../projects/visibleProjectFeatures.js";
import { PledgeButton } from "./PledgeButton";
import { ProjectFundProgress } from "./ProjectFundProgress";

/** Même plafond que ProjectList.js BI (slice 0, 100). */
const LIST_CAP = 100;
const MIN_EUR = "1.00";

function ProjectPledgeForm({ project, contributor, onAuthorized }) {
  const { t } = useTranslation();
  const props = project?.properties || {};
  const [amount, setAmount] = useState(MIN_EUR);
  const [who, setWho] = useState(contributor || "");
  const [publicTotal, setPublicTotal] = useState(null);
  const title = props.title || props.id || "";
  const description = t("projects.pledgeDescription", { title });
  const parsed = parseProjectPledgeAmount(amount);
  const isGear = String(props.project_kind || "") === "gear_project";
  const projectId = String(props.id || "").trim();

  const loadFund = useCallback(async () => {
    if (!isGear || !projectId) {
      setPublicTotal(null);
      return;
    }
    const data = await fetchPublicProjectFund(projectId);
    setPublicTotal(data);
  }, [isGear, projectId]);

  useEffect(() => {
    void loadFund();
  }, [loadFund]);

  const handleAuthorized = (pledge) => {
    void loadFund();
    onAuthorized?.(pledge);
  };

  return (
    <div className="project-pledge" data-testid="project-pledge" data-project-id={props.id}>
      {isGear && publicTotal ? (
        <ProjectFundProgress properties={props} fund={publicTotal} />
      ) : null}
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
      {parsed.kind === "invalid" ? <p className="notice warn">{t("projects.invalidAmount")}</p> : null}
      {parsed.kind === "empty" || parsed.kind === "below_min" ? (
        <p className="notice warn">{t("projects.minAmount")}</p>
      ) : null}
      <PledgeButton
        values={{
          amount_eur: parsed.apiAmount || MIN_EUR,
          description,
          milestone_id: "",
          contributor: who.trim() || undefined,
          kind: "project_pledge",
          target_id: props.id,
        }}
        disabled={parsed.kind !== "ok"}
        onAuthorized={handleAuthorized}
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
  const { t, i18n } = useTranslation();
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

  const features = useMemo(
    () => visibleProjectFeatures(projects?.features || [], filtered, selectedProjectId, LIST_CAP),
    [projects, filtered, selectedProjectId],
  );
  const truncated = filtered.length > LIST_CAP;
  const formatCount = (count) => new Intl.NumberFormat(i18n.language || "fr").format(count);

  return (
    <section className="panel" data-testid="project-list">
      <div className="escale-sheet-head">
        <h2>{t("projects.heading")}</h2>
        <span className="project-list-total" data-testid="project-list-count">
          {formatCount(projects?.features?.length || 0)}
        </span>
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
          {t("projects.truncated", { shown: formatCount(LIST_CAP), total: formatCount(filtered.length) })}
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

/**
 * Liste des projets. Copie adaptée de
 * Blue-Intelligence frontend/src/components/ProjectList.js
 * (filtres laissés au caller ; pas de SwarmPanel).
 */
import { useTranslation } from "react-i18next";

export default function ProjectList({ projects, funderFilter = "All", searchQuery = "", categoryFilter = "All", onFlyTo }) {
  const { t } = useTranslation();
  const q = (searchQuery || "").toLowerCase();
  const features = (projects?.features || []).filter((feature) => {
    const props = feature.properties || {};
    return (funderFilter === "All" || (props.funder || "").includes(funderFilter))
      && (categoryFilter === "All" || props.category_group === categoryFilter)
      && (!q || `${props.title} ${props.description} ${props.funder} ${props.location || ""}`.toLowerCase().includes(q));
  });

  return (
    <section className="panel" data-testid="project-list">
      <div className="escale-sheet-head">
        <h2>{t("projects.heading")}</h2>
        <span>{features.length}</span>
      </div>
      {features.length === 0 ? <p className="hint">{t("projects.empty")}</p> : null}
      <div>
        {features.slice(0, 100).map((feature) => {
          const props = feature.properties;
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
              {props.url ? (
                <a href={props.url} target="_blank" rel="noreferrer">
                  {t("projects.open")}
                </a>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

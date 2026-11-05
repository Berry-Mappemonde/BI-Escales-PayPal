/**
 * Liste des marinas. Dérivée de Blue Intelligence frontend/src/components/MarinasPanel.js.
 * Les sondages /marinas/build, /anchorages/build et /maps-place sont retirés
 * (pas d'écran de construction). La légende des couches absentes aussi.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { PledgeButton } from "./PledgeButton";

const BERTH_EUR = "30.00";

export default function MarinasPanel({ marinas, onFlyTo, milestoneId, contributor, onAuthorized }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [pickedId, setPickedId] = useState(null);
  const features = marinas?.features || [];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return features;
    return features.filter((feature) => {
      const props = feature.properties || {};
      return (
        (props.name || "").toLowerCase().includes(q)
        || String(props.osm_id || "").toLowerCase().includes(q)
      );
    });
  }, [features, query]);

  const verifiedCount = useMemo(
    () => features.filter((f) => f.properties?.safe_google_place).length,
    [features],
  );

  return (
    <aside className="panel marinas-panel" data-testid="marinas-panel">
      <div className="escale-sheet-head">
        <h2>{t("marinas.heading")}</h2>
        <span data-testid="marinas-count">{features.length}</span>
      </div>
      <div className="marinas-legend" data-testid="marinas-legend">
        <p className="hint marinas-legend-title">{t("marinas.legendHeading")}</p>
        <ul className="marinas-legend-list">
          <li>
            <span className="marinas-legend-swatch marinas-legend-swatch--verified" aria-hidden />
            {t("marinas.legendVerified")}
            {verifiedCount ? ` (${verifiedCount})` : ""}
          </li>
          <li>
            <span className="marinas-legend-swatch marinas-legend-swatch--default" aria-hidden />
            {t("marinas.legendDefault")}
          </li>
        </ul>
      </div>
      <input
        data-testid="marinas-search-input"
        type="text"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("marinas.search")}
        aria-label={t("marinas.search")}
      />
      <div data-testid="marinas-list">
        {features.length === 0 ? <p className="hint">{t("marinas.empty")}</p> : null}
        {filtered.map((feature) => {
          const props = feature.properties || {};
          const [lon, lat] = feature.geometry?.coordinates || [0, 0];
          const verified = Boolean(props.safe_google_place);
          return (
            <div key={props.id || props.osm_id}>
              <button
                type="button"
                data-testid={`marina-row-${props.id}`}
                className={`marina-row${verified ? " marina-row--verified" : ""}`}
                onClick={() => {
                  setPickedId(props.id || props.osm_id);
                  onFlyTo?.(props.id, lat, lon);
                }}
              >
                <strong>{props.name || t("marinas.unnamed")}</strong>
                <span className="hint">{props.osm_id || `${Number(lat).toFixed(3)}, ${Number(lon).toFixed(3)}`}</span>
              </button>
              {pickedId === (props.id || props.osm_id) ? (
                <div data-testid="marina-reserve" data-kind="berth">
                  <p className="hint">{t("marinas.reservePrice")}</p>
                  <p>{t("marinas.reserveDescription", { name: props.name || t("marinas.unnamed") })}</p>
                  <PledgeButton
                    values={{
                      amount_eur: BERTH_EUR,
                      description: t("marinas.reserveDescription", { name: props.name || t("marinas.unnamed") }),
                      milestone_id: milestoneId || "",
                      contributor: contributor || undefined,
                      kind: "berth",
                      target_id: milestoneId || "",
                    }}
                    disabled={!milestoneId}
                    onAuthorized={onAuthorized}
                  />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <p className="hint">
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          {t("marinas.odbl")}
        </a>
      </p>
    </aside>
  );
}

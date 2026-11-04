import { X } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { scienceKindLabel } from "../layers/scienceLabels.js";
import { localizeStoredTitle } from "./iciMaintenant.js";

function hostLabel(url) {
  try {
    return String(url).replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 48);
  } catch {
    return String(url || "").slice(0, 48);
  }
}

function Row({ label, children }) {
  if (!children) return null;
  return (
    <div className="muted" style={{ marginTop: 6 }}>
      {label ? <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>{label}</div> : null}
      {children}
    </div>
  );
}

export function LayerFichePopup({ popup, onClose }) {
  const { lang, t } = useLang();
  if (!popup) return null;
  const { kind, props = {} } = popup;
  const clusterCount = Number(props.clusterCount) || 1;
  let title = props.name || props.title || props.GEONAME || props.geoname || props.portName || "—";
  let subtitle = "";
  let extra = null;

  if (kind === "zee") {
    title = localizeStoredTitle(props.GEONAME || props.geoname || props.name || "", lang) || t("layerFicheEez");
    subtitle = [props.TERRITORY1 || props.territory1, props.POL_TYPE || props.pol_type, props.ISO_TER1].filter(Boolean).join(" · ");
  } else if (kind === "marina") {
    subtitle = props.country || "";
    extra = (
      <>
        <Row label={t("layerFicheSite")}>{props.website ? <a href={props.website} target="_blank" rel="noreferrer">{hostLabel(props.website)}</a> : null}</Row>
        <Row>{props.telephone}</Row>
      </>
    );
  } else if (kind === "project") {
    const name = props.title || props.name;
    title = name ? (lang.startsWith("en") ? `Project: ${name}` : name) : t("layerFicheProject");
    subtitle = [props.funder, props.category_group].filter(Boolean).join(" · ");
    extra = (
      <>
        {props.description ? <p className="muted" style={{ margin: "6px 0" }}>{props.description}</p> : null}
        {props.url ? <a href={props.url} target="_blank" rel="noreferrer">{t("layerFicheSeeProject")}</a> : null}
      </>
    );
  } else if (kind === "capitainerie") {
    extra = (
      <>
        <Row label={t("layerFichePhone")}>{props.telephone ? <a href={`tel:${props.telephone}`}>{props.telephone}</a> : null}</Row>
        <Row label={t("layerFicheVhf")}>{props.canal_vhf}</Row>
        <Row label={t("layerFicheSite")}>{props.website ? <a href={props.website} target="_blank" rel="noreferrer">{hostLabel(props.website)}</a> : null}</Row>
      </>
    );
  } else if (kind === "poe") {
    title = props.name || t("layerFichePortOfEntry");
    subtitle = [props.country, props.spatial_kind].filter(Boolean).join(" · ");
    extra = props.source_urls?.[0]
      ? <a href={props.source_urls[0]} target="_blank" rel="noreferrer">{hostLabel(props.source_urls[0])}</a>
      : null;
  } else if (kind === "amp") {
    title = props.name || props.site_id || t("layerFicheMpa");
    subtitle = [props.designation, props.country].filter(Boolean).join(" · ");
    extra = (
      <>
        {props.lfp != null ? <div className="muted" style={{ marginTop: 6 }}>LFP {props.lfp}</div> : null}
        {props.manager_url ? <Row label={t("layerFicheManager")}><a href={props.manager_url} target="_blank" rel="noreferrer">{hostLabel(props.manager_url)}</a></Row> : null}
        {props.visit_url ? <Row label={t("layerFicheVisit")}><a href={props.visit_url} target="_blank" rel="noreferrer">{hostLabel(props.visit_url)}</a></Row> : null}
      </>
    );
  } else if (kind === "port") {
    subtitle = [props.country, props.region].filter(Boolean).join(" · ");
  } else if (kind === "science") {
    title = props.name || props.title || t("layerFicheScience");
    subtitle = [props.source, scienceKindLabel(props.kind, t), props.provider].filter(Boolean).join(" · ");
    extra = (
      <>
        {props.wmo ? <Row label="WMO">{String(props.wmo)}</Row> : null}
        {props.ship ? <Row label={t("layerFicheShip")}>{props.ship}</Row> : null}
        {props.url ? <a href={props.url} target="_blank" rel="noreferrer">{hostLabel(props.url)}</a> : null}
      </>
    );
  }

  // A grouped cell is named by its count, in the reader's language, and shows
  // nothing of one of its points (site, phone, link) as if it held for all.
  if (clusterCount > 1) {
    title = t("layerFicheCluster", { count: clusterCount });
    subtitle = "";
    extra = <div className="muted" style={{ marginTop: 6 }}>{t("layerFicheClusterZoom")}</div>;
  }

  return (
    <div
      className="absolute left-1/2 -translate-x-1/2 z-[2100] layer-fiche-popup shadow-2xl"
      data-testid="layer-fiche"
    >
      <button type="button" onClick={onClose} aria-label={t("layerFicheClose")} title={t("layerFicheClose")} className="absolute top-2 right-2 text-slate-400 hover:text-white">
        <X size={14} />
      </button>
      <h3>{localizeStoredTitle(title, lang)}</h3>
      {subtitle ? <div className="muted">{subtitle}</div> : null}
      {extra}
    </div>
  );
}

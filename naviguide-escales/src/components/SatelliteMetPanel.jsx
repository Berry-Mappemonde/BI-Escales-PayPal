import { WindDirectionArrow } from "./map/WindDirectionArrow";
import {
  formatBearingCardinal,
  formatCardinal,
  formatCellLabel,
  formatMetNumber,
  formatMetTime,
} from "../utils/satelliteMet.js";

function Row({ label, value }) {
  if (value == null || value === "") return null;
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-400 shrink-0">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function CardinalRows({ degrees, dirLabel, t, lang = "fr" }) {
  const cardFr = formatCardinal(degrees, "fr");
  const card = formatCardinal(degrees, lang);
  const spelled = cardFr ? t(`cardinal${cardFr}`) : "";
  return (
    <>
      <Row
        label={t("satelliteCardinal")}
        value={card ? `${card} — ${spelled}` : null}
      />
      <Row label={dirLabel} value={formatBearingCardinal(degrees, lang)} />
    </>
  );
}

function sharedRows(product, t) {
  const src = product.simulation
    ? t("satelliteEstimated")
    : (product.source && !String(product.source).startsWith("estimated")
      ? product.source
      : t("satelliteCopernicus"));
  return (
    <>
      <Row
        label={t("satelliteLat")}
        value={formatMetNumber(product.latitude, 4) && `${formatMetNumber(product.latitude, 4)}°`}
      />
      <Row
        label={t("satelliteLon")}
        value={formatMetNumber(product.longitude, 4) && `${formatMetNumber(product.longitude, 4)}°`}
      />
      <Row label={t("satelliteIssued")} value={formatMetTime(product.timestamp)} />
      <Row label={t("satelliteSource")} value={src} />
      <Row label={t("satelliteCycle")} value={product.cycle} />
      <Row label={t("satelliteCell")} value={formatCellLabel(product.cell)} />
    </>
  );
}

export function SatelliteMetPanel({ kind, product, t, lang = "fr" }) {
  if (kind === "wind") {
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <WindDirectionArrow direction={product.wind_direction} />
          <span>{t("windSpeed")} {formatMetNumber(product.wind_speed_knots, 1)} kt</span>
        </div>
        <Row label={t("windSpeedKmh")} value={formatMetNumber(product.wind_speed_kmh, 1) && `${formatMetNumber(product.wind_speed_kmh, 1)} km/h`} />
        <Row label={t("windSpeedMs")} value={formatMetNumber(product.wind_speed, 2) && `${formatMetNumber(product.wind_speed, 2)} m/s`} />
        <CardinalRows degrees={product.wind_direction} dirLabel={t("windDirection")} t={t} lang={lang} />
        <Row label={t("currentEast")} value={formatMetNumber(product.u_component, 3) && `${formatMetNumber(product.u_component, 3)} m/s`} />
        <Row label={t("currentNorth")} value={formatMetNumber(product.v_component, 3) && `${formatMetNumber(product.v_component, 3)} m/s`} />
        {sharedRows(product, t)}
      </div>
    );
  }

  if (kind === "wave") {
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <WindDirectionArrow direction={product.mean_wave_direction} />
          <span>{t("waveHeight")} {formatMetNumber(product.significant_wave_height_m, 2)} m</span>
        </div>
        <Row
          label={t("wavePeriod")}
          value={formatMetNumber(product.mean_wave_period, 1) && `${formatMetNumber(product.mean_wave_period, 1)} s`}
        />
        <CardinalRows degrees={product.mean_wave_direction} dirLabel={t("waveDirection")} t={t} lang={lang} />
        {sharedRows(product, t)}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <WindDirectionArrow direction={product.direction_deg} />
        <span>{t("currentSurfaceSpeed")} {formatMetNumber(product.speed_knots, 2)} kt</span>
      </div>
      <Row label={t("currentSpeedKmh")} value={formatMetNumber(product.speed_kmh, 2) && `${formatMetNumber(product.speed_kmh, 2)} km/h`} />
      <Row label={t("currentSpeedMs")} value={formatMetNumber(product.speed_ms, 3) && `${formatMetNumber(product.speed_ms, 3)} m/s`} />
      <CardinalRows degrees={product.direction_deg} dirLabel={t("currentDirection")} t={t} lang={lang} />
      <Row label={t("currentEast")} value={formatMetNumber(product.u_component, 4) && `${formatMetNumber(product.u_component, 4)} m/s`} />
      <Row label={t("currentNorth")} value={formatMetNumber(product.v_component, 4) && `${formatMetNumber(product.v_component, 4)} m/s`} />
      {sharedRows(product, t)}
    </div>
  );
}

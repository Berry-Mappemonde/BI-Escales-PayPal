import { useTranslation } from "react-i18next";

export type MapLayerId = "projects" | "marinas";
export type MapLayers = Record<MapLayerId, boolean>;

const LAYER_IDS: MapLayerId[] = ["projects", "marinas"];

export interface MapLayerControlProps {
  layers: MapLayers;
  onToggle: (id: MapLayerId) => void;
}

/**
 * The map's two optional layers, as toggles under the zoom buttons. The route and
 * the stop flags are not listed: they are the map's subject and always drawn.
 */
export function MapLayerControl({ layers, onToggle }: MapLayerControlProps) {
  const { t } = useTranslation();
  return (
    <div className="ng-layer-control" role="group" aria-label={t("map.layers")} data-testid="map-layer-control">
      {LAYER_IDS.map((id) => (
        <button
          key={id}
          type="button"
          className="ng-layer-toggle"
          data-layer={id}
          data-testid={`map-layer-${id}`}
          aria-pressed={layers[id]}
          onClick={() => onToggle(id)}
        >
          <span className="ng-layer-swatch" aria-hidden="true" />
          {t(id === "projects" ? "map.layerProjects" : "map.layerMarinas")}
        </button>
      ))}
    </div>
  );
}

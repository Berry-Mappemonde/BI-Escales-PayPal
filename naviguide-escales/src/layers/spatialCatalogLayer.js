import L from "leaflet";
import { circleOpts } from "./points.js";
import {
  catalogPointRadiusPx,
  ficheFromHit,
  isClusterFeature,
  pickCatalogHit,
} from "./catalogHit.js";
import { paneZIndex } from "./layerOrder.js";
import { catalogMayTakeClick, featureStamp, releaseCatalogPick } from "./catalogStamp.js";
import {
  worldCopyLineCoords,
  worldCopyLngs,
  worldCopyPolygonCoords,
} from "../utils/geo.js";
import { LAYER_DRAW_CAPS, pointsWithinDrawCap } from "../engine/layerWarm.js";

const catalogLayers = new Set();

function installCatalogPick(map) {
  if (!map || map._biCatalogPick) return;
  const onClick = (domEvent) => {
    if (map._biSuspendCatalogPick) return;
    if (domEvent.button != null && domEvent.button !== 0) return;
    const target = domEvent.target;
    if (!(target instanceof Element)) return;
    if (!catalogMayTakeClick(target)) return;
    const latlng = map.mouseEventToLatLng(domEvent);
    if (!latlng) return;
    const zoom = map.getZoom();
    const project = (lon, lat) => {
      const point = map.latLngToContainerPoint([lat, lon]);
      return { x: point.x, y: point.y };
    };
    const entries = [];
    let order = 0;
    catalogLayers.forEach((layer) => {
      if (layer.map !== map) return;
      const z = paneZIndex(layer.pane);
      (layer.features || []).forEach((feature) => {
        const clusterCount = Number(feature?.properties?.clusterCount) || 1;
        entries.push({
          feature,
          kind: layer.kind,
          z,
          order,
          radiusPx: feature?.geometry?.type === "Point"
            ? catalogPointRadiusPx(zoom, clusterCount)
            : 8,
          layer,
        });
        order += 1;
      });
    });
    const hit = pickCatalogHit(entries, latlng.lat, latlng.lng, project);
    if (!hit) return;
    domEvent.stopPropagation();
    if (isClusterFeature(hit.feature)) {
      map.setView(
        latlng,
        Math.min(map.getMaxZoom(), zoom + 2),
        { animate: true },
      );
    }
    hit.layer.onFeature?.(ficheFromHit(hit, latlng.lat, latlng.lng));
  };
  map.getContainer().addEventListener("click", onClick, true);
  map._biCatalogPick = onClick;
}

function latLngs(coords) {
  return (coords || []).map(([lon, lat]) => [lat, lon]);
}

function geometryLatLngCopies(geometry = {}) {
  switch (geometry.type) {
    case "LineString":
      return worldCopyLineCoords(geometry.coordinates).map(latLngs);
    case "MultiLineString":
      return (geometry.coordinates || []).flatMap((line) => (
        worldCopyLineCoords(line).map(latLngs)
      ));
    case "Polygon":
      return worldCopyPolygonCoords(geometry.coordinates).map((rings) => rings.map(latLngs));
    case "MultiPolygon":
      return (geometry.coordinates || []).flatMap((polygon) => (
        worldCopyPolygonCoords(polygon).map((rings) => rings.map(latLngs))
      ));
    default:
      return [];
  }
}

function isPolygon(type) {
  return type === "Polygon" || type === "MultiPolygon";
}

/**
 * Groupe durable pour un catalogue : un pan ne recrée que les features
 * entrées/sorties du viewport, les objets encore visibles sont patchés.
 */
export class SpatialCatalogLayer {
  constructor(map, {
    color,
    kind,
    pane,
    pointFillOpacity,
    styleFor,
    onFeature,
  } = {}) {
    this.map = map;
    this.group = L.layerGroup().addTo(map);
    this.renderer = L.canvas({ padding: 0.5, tolerance: 8 });
    this.records = new Map();
    this.features = [];
    this.configure({ color, kind, pane, pointFillOpacity, styleFor, onFeature });
    catalogLayers.add(this);
    installCatalogPick(map);
  }

  configure({ color, kind, pane, pointFillOpacity, styleFor, onFeature } = {}) {
    this.color = color || this.color || "#38bdf8";
    this.kind = kind || this.kind || "catalog";
    this.pane = pane || this.pane;
    this.pointFillOpacity = pointFillOpacity ?? this.pointFillOpacity ?? 0.8;
    this.styleFor = styleFor || this.styleFor;
    this.onFeature = onFeature || this.onFeature;
  }

  _featureKey(feature, index) {
    return String(feature?.properties?.naviguideCatalogId || `${this.kind}:${index}`);
  }

  _pointOptions(feature) {
    const clusterCount = Number(feature?.properties?.clusterCount) || 1;
    return circleOpts(this.color, {
      zoom: this.map.getZoom(),
      bump: clusterCount > 1 ? Math.min(6, Math.log2(clusterCount)) : 0,
      fillOpacity: this.pointFillOpacity,
      renderer: this.renderer,
      ...(this.pane ? { pane: this.pane } : {}),
    });
  }

  _shapeOptions(feature) {
    const style = this.styleFor?.(feature?.properties || {}) || {};
    return {
      color: this.color,
      weight: 2.5,
      opacity: 0.85,
      fillOpacity: isPolygon(feature?.geometry?.type) ? 0.12 : 0,
      ...(this.pane ? { pane: this.pane } : {}),
      ...style,
    };
  }

  _addFeatureLayers(group, feature) {
    const geometry = feature?.geometry || {};
    if (geometry.type === "Point") {
      const [lon, lat] = geometry.coordinates || [];
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      worldCopyLngs(lon).forEach((copyLon) => {
        const layer = L.circleMarker([lat, copyLon], this._pointOptions(feature));
        group.addLayer(layer);
      });
      return;
    }

    const copies = geometryLatLngCopies(geometry);
    copies.forEach((latlngs) => {
      if (!latlngs.length) return;
      const layer = isPolygon(geometry.type)
        ? L.polygon(latlngs, this._shapeOptions(feature))
        : L.polyline(latlngs, this._shapeOptions(feature));
      group.addLayer(layer);
    });
  }

  _create(feature) {
    const geometry = feature?.geometry || {};
    const layer = L.layerGroup();
    this._addFeatureLayers(layer, feature);
    if (!layer.getLayers().length) return null;
    this.group.addLayer(layer);
    return { layer, type: geometry.type, feature, stamp: featureStamp(feature, this.map.getZoom()) };
  }

  _update(record, feature) {
    const geometry = feature?.geometry || {};
    const stamp = featureStamp(feature, this.map.getZoom());
    if (record.stamp === stamp && record.type === geometry.type) {
      record.feature = feature;
      return record;
    }
    if (record.type !== geometry.type) {
      this.group.removeLayer(record.layer);
      return this._create(feature);
    }
    record.layer.clearLayers();
    this._addFeatureLayers(record.layer, feature);
    if (!record.layer.getLayers().length) return null;
    record.feature = feature;
    record.stamp = stamp;
    return record;
  }

  update(featureCollection) {
    const drawn = pointsWithinDrawCap(
      featureCollection?.features || [],
      this.map?.getZoom?.(),
      LAYER_DRAW_CAPS.point,
    );
    this.features = drawn;
    const next = new Map();
    drawn.forEach((feature, index) => {
      const key = this._featureKey(feature, index);
      const existing = this.records.get(key);
      const record = existing ? this._update(existing, feature) : this._create(feature);
      if (record) next.set(key, record);
    });
    this.records.forEach((record, key) => {
      if (!next.has(key)) this.group.removeLayer(record.layer);
    });
    this.records = next;
  }

  remove() {
    catalogLayers.delete(this);
    this.features = [];
    this.group.remove();
    this.records.clear();
    // The last catalog on this map takes its click listener with it.
    releaseCatalogPick(this.map, catalogLayers);
  }
}

/**
 * Small lifecycle registry for Leaflet objects owned by a MapScene.
 * A layer is created once, updated in place, then explicitly removed.
 */
export class SceneLayerRegistry {
  constructor() {
    this.entries = new Map();
  }

  add(name, create) {
    const existing = this.entries.get(name);
    if (existing) return existing;
    const layer = create();
    this.entries.set(name, layer);
    return layer;
  }

  update(name, create, apply) {
    const layer = this.add(name, create);
    apply(layer);
    return layer;
  }

  remove(name) {
    const layer = this.entries.get(name);
    if (!layer) return;
    layer.remove?.();
    this.entries.delete(name);
  }

  clear() {
    [...this.entries.keys()].forEach((name) => this.remove(name));
  }
}

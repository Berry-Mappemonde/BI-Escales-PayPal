import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { SceneLayerRegistry } from "./SceneLayerRegistry.js";

describe("SceneLayerRegistry", () => {
  it("crée une fois, met à jour et retire explicitement un calque", () => {
    const registry = new SceneLayerRegistry();
    const layer = {
      value: null,
      removed: 0,
      remove() { this.removed += 1; },
    };
    let creations = 0;
    const create = () => {
      creations += 1;
      return layer;
    };

    registry.update("wake", create, (entry) => { entry.value = "first"; });
    registry.update("wake", create, (entry) => { entry.value = "second"; });

    assert.equal(creations, 1);
    assert.equal(layer.value, "second");
    registry.remove("wake");
    assert.equal(layer.removed, 1);
  });

  it("détruit tous les calques restants", () => {
    const registry = new SceneLayerRegistry();
    const first = { removed: 0, remove() { this.removed += 1; } };
    const second = { removed: 0, remove() { this.removed += 1; } };
    registry.add("route", () => first);
    registry.add("markers", () => second);

    registry.clear();

    assert.equal(first.removed, 1);
    assert.equal(second.removed, 1);
  });
});

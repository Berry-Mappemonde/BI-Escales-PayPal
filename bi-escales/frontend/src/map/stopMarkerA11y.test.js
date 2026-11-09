import L from "leaflet";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindStopMarkerKeyboard } from "./stopMarkerA11y.js";

describe("bindStopMarkerKeyboard", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("activates the stop on Enter and Space after addTo (no manual add event)", () => {
    const onActivate = vi.fn();
    const stop = { milestoneId: "dep-la-rochelle", name: "La Rochelle" };

    const mapEl = document.createElement("div");
    mapEl.style.width = "640px";
    mapEl.style.height = "480px";
    document.body.appendChild(mapEl);

    const map = L.map(mapEl, { zoomControl: false, attributionControl: false }).setView([46.16, -1.15], 8);
    const group = L.layerGroup().addTo(map);

    const marker = L.marker([46.16, -1.15], {
      icon: L.divIcon({
        className: "flag-divicon",
        html: '<div data-stop-marker="true" role="button" tabindex="0" aria-label="test"></div>',
      }),
      stopData: stop,
    }).addTo(group);

    bindStopMarkerKeyboard(marker, stop, onActivate);

    const control = marker.getElement().querySelector("[data-stop-marker]");
    expect(control).toBeTruthy();
    control.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    control.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));

    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(onActivate).toHaveBeenCalledWith(stop);
  });
});

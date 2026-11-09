import L from "leaflet";
import { describe, expect, it, vi } from "vitest";
import { bindStopMarkerKeyboard } from "./stopMarkerA11y.js";

describe("bindStopMarkerKeyboard", () => {
  it("activates the stop on Enter and Space", () => {
    const onActivate = vi.fn();
    const stop = { milestoneId: "dep-la-rochelle", name: "La Rochelle" };
    const control = document.createElement("div");
    control.setAttribute("data-stop-marker", "true");
  control.setAttribute("role", "button");
    const root = document.createElement("div");
    root.appendChild(control);

    const marker = L.marker([46.16, -1.15], {
      icon: L.divIcon({
        className: "flag-divicon",
        html: '<div data-stop-marker="true" role="button" tabindex="0" aria-label="test"></div>',
      }),
      stopData: stop,
    });
    marker.getElement = () => root;
    bindStopMarkerKeyboard(marker, stop, onActivate);
    marker.fire("add");

    control.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    control.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));

    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(onActivate).toHaveBeenCalledWith(stop);
  });
});

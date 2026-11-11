import { render, waitFor } from "@testing-library/react";
import L from "leaflet";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { MapScene, popupWidths } from "./MapScene.jsx";

vi.mock("../components/ProjectMapPopup.jsx", () => ({
  ProjectMapPopup: ({ properties }) => <div data-testid="project-popup">{properties.title}</div>,
}));
vi.mock("../components/MarinaMapPopup.jsx", () => ({
  MarinaMapPopup: ({ properties }) => <div data-testid="marina-popup">{properties.name}</div>,
}));

const point = (lon, lat, properties) => ({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties });
const projects = {
  type: "FeatureCollection",
  features: [point(1, 2, { id: "p-1", title: "Reef survey" }), point(3, 4, { id: "p-2", title: "Plastics Initiative" })],
};
const marinas = { type: "FeatureCollection", features: [point(-1.15, 46.15, { id: "m-1", name: "Bassin des Tamaris" })] };
const stops = [{ name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: "dep-la-rochelle", flags: ["/flags/fr.svg"] }];
const segments = [{ coords: [[1.6, 46.8], [-1.15, 46.16]] }];
const mapOf = (width) => ({ getSize: () => ({ x: width, y: 800 }) });

describe("popupWidths", () => {
  it("keeps the designed widths on a desktop map", () => {
    expect(popupWidths(mapOf(1100), 360, 260)).toEqual({ maxWidth: 360, minWidth: 260 });
    expect(popupWidths(mapOf(1100), 320)).toEqual({ maxWidth: 320 });
  });

  it("narrows the popup to fit a phone map, frame and side room included", () => {
    const project = popupWidths(mapOf(390), 360, 260);
    expect(project).toEqual({ maxWidth: 302, minWidth: 260 });
    expect(project.maxWidth + 40 + 48).toBeLessThanOrEqual(390);
    expect(popupWidths(mapOf(390), 320)).toEqual({ maxWidth: 302 });
  });

  it("never asks for a minimum above the maximum", () => {
    expect(popupWidths(mapOf(320), 360, 260)).toEqual({ maxWidth: 232, minWidth: 232 });
    expect(popupWidths(mapOf(200), 360, 260)).toEqual({ maxWidth: 160, minWidth: 160 });
  });

  it("uses the designed widths when the map has no size yet", () => {
    expect(popupWidths(mapOf(0), 360, 260)).toEqual({ maxWidth: 360, minWidth: 260 });
    expect(popupWidths(null, 320)).toEqual({ maxWidth: 320 });
  });
});

describe("MapScene popups", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  function scene(props) {
    return (
      <I18nextProvider i18n={i18n}>
        <MapScene segments={segments} stops={stops} boat={null} projects={projects} marinas={marinas} theme="dark" showProjects showMarinas {...props} />
      </I18nextProvider>
    );
  }

  it("opens a project's popup when the project is picked outside the map", async () => {
    const view = render(scene({ flyTo: null }));
    expect(document.querySelector(".leaflet-popup")).toBeNull();

    view.rerender(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 1 } }));
    await waitFor(() => expect(document.querySelector('[data-testid="project-popup"]')).not.toBeNull());
    expect(document.querySelector('[data-testid="project-popup"]').textContent).toBe("Plastics Initiative");
    expect(document.querySelectorAll(".leaflet-popup")).toHaveLength(1);
  });

  it("opens nothing for a target that is not a project (a stop, the boat, a marina)", async () => {
    const view = render(scene({ flyTo: null }));
    view.rerender(scene({ flyTo: { lat: 46.16, lon: -1.15, ts: 2 } }));
    view.rerender(scene({ flyTo: { id: "m-1", lat: 46.15, lon: -1.15, ts: 3 } }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.querySelector(".leaflet-popup")).toBeNull();
  });

  it("opens nothing when the project layer is off", async () => {
    const view = render(scene({ flyTo: null, showProjects: false }));
    view.rerender(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 4 }, showProjects: false }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.querySelector(".leaflet-popup")).toBeNull();
  });

  it("keeps a project's popup open when the dots are rebuilt with a longer list", async () => {
    const view = render(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 6 } }));
    await waitFor(() => expect(document.querySelector('[data-testid="project-popup"]')).not.toBeNull());

    // The gear projects arrive: same base projects, new object, more rows.
    const longer = { ...projects, features: [point(5, 6, { id: "g-1", title: "Life raft" }), ...projects.features] };
    view.rerender(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 6 }, projects: longer }));
    await waitFor(() => expect(document.querySelector('[data-testid="project-popup"]')?.textContent).toBe("Plastics Initiative"));
    expect(document.querySelectorAll(".leaflet-popup")).toHaveLength(1);

    // A project that is gone from the list takes its popup with it.
    view.rerender(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 6 }, projects: { ...projects, features: [projects.features[0]] } }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.querySelector(".leaflet-popup")).toBeNull();
  });

  it("measures a popup again once its content is on the page", async () => {
    const layout = vi.spyOn(L.Popup.prototype, "_updateLayout");
    const view = render(scene({ flyTo: null }));
    view.rerender(scene({ flyTo: { id: "p-1", lat: 2, lon: 1, ts: 5 } }));
    await waitFor(() => expect(document.querySelector('[data-testid="project-popup"]')).not.toBeNull());
    // Leaflet lays the popup out once on open; the second layout is the refit.
    await waitFor(() => expect(layout.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("refits on every change of the content's size where the browser can report it", async () => {
    const observers = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback) {
          this.callback = callback;
          this.disconnect = vi.fn();
          observers.push(this);
        }
        observe(target) {
          this.target = target;
        }
      },
    );
    try {
      const layout = vi.spyOn(L.Popup.prototype, "_updateLayout");
      const reattach = vi.spyOn(L.Popup.prototype, "_updateContent");
      const view = render(scene({ flyTo: null }));
      view.rerender(scene({ flyTo: { id: "p-1", lat: 2, lon: 1, ts: 7 } }));
      await waitFor(() => expect(document.querySelector('[data-testid="project-popup"]')).not.toBeNull());
      const watching = observers.filter((entry) => entry.target?.classList?.contains("project-map-popup"));
      expect(watching).toHaveLength(1);
      const [observer] = watching;
      const before = layout.mock.calls.length;
      const reattached = reattach.mock.calls.length;

      const size = (w, h) => {
        Object.defineProperty(observer.target, "offsetWidth", { configurable: true, value: w });
        Object.defineProperty(observer.target, "offsetHeight", { configurable: true, value: h });
      };
      size(233, 300);
      observer.callback();
      expect(layout.mock.calls.length).toBe(before + 1);
      observer.callback(); // same size again: nothing to do
      expect(layout.mock.calls.length).toBe(before + 1);
      size(233, 420); // the PayPal button arrived
      observer.callback();
      expect(layout.mock.calls.length).toBe(before + 2);
      // Re-attaching the content node would reload the PayPal iframe inside it.
      expect(reattach.mock.calls.length).toBe(reattached);

      // Closing the popup stops the watching.
      view.rerender(scene({ flyTo: { id: "p-2", lat: 4, lon: 3, ts: 8 } }));
      await waitFor(() => expect(observer.disconnect).toHaveBeenCalled());
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

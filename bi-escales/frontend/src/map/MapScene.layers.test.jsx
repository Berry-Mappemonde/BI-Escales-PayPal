import { render, waitFor } from "@testing-library/react";
import L from "leaflet";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { LAYER_PANES, MapScene } from "./MapScene.jsx";

const point = (lon, lat, properties) => ({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties });
const projects = { type: "FeatureCollection", features: [point(1, 2, { id: "p-1", title: "Reef survey" })] };
const marinas = {
  type: "FeatureCollection",
  features: [
    point(-1.15, 46.15, { id: "m-1", name: "Bassin des Tamaris" }),
    point(-1.16, 46.14, { id: "m-2", name: "Port des Minimes", safe_google_place: true }),
  ],
};
const stops = [{ name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: "dep-la-rochelle", flags: ["/flags/fr.svg"] }];
const segments = [{ coords: [[1.6, 46.8], [-1.15, 46.16]] }];

describe("MapScene layers", () => {
  const circles = [];

  beforeEach(async () => {
    circles.length = 0;
    await i18n.changeLanguage("en");
    const orig = L.circleMarker.bind(L);
    vi.spyOn(L, "circleMarker").mockImplementation((latlng, options) => {
      circles.push(options);
      return orig(latlng, options);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  function scene(props) {
    return (
      <I18nextProvider i18n={i18n}>
        <MapScene segments={segments} stops={stops} boat={null} projects={projects} marinas={marinas} theme="dark" {...props} />
      </I18nextProvider>
    );
  }

  const paneZ = (name) => Number(document.querySelector(`.leaflet-${name}-pane`).style.zIndex);

  it("draws both layers under the route and the stop flags", async () => {
    render(scene({ showProjects: true, showMarinas: true }));
    await waitFor(() => expect(circles.length).toBe(3));

    expect(circles.filter((options) => options.pane === LAYER_PANES.projects)).toHaveLength(1);
    expect(circles.filter((options) => options.pane === LAYER_PANES.marinas)).toHaveLength(2);

    const route = paneZ("route");
    expect(paneZ(LAYER_PANES.projects)).toBeLessThan(route);
    expect(paneZ(LAYER_PANES.marinas)).toBeLessThan(route);
    expect(paneZ(LAYER_PANES.projects)).toBeLessThan(paneZ(LAYER_PANES.marinas));
    // Leaflet's marker pane (the flags) keeps its 600, above the route's 380.
    expect(route).toBeLessThan(600);
    expect(document.querySelectorAll(".leaflet-marker-pane .flag-divicon").length).toBeGreaterThan(0);
  });

  it("takes the marina colours from the tokens, not from the code", async () => {
    render(scene({ showProjects: false, showMarinas: true }));
    await waitFor(() => expect(circles.length).toBe(2));
    expect(circles.map((options) => options.className)).toEqual(["marina-dot", "marina-dot marina-dot--verified"]);
    for (const options of circles) {
      expect(options.color).toBe("currentColor");
      expect(options.fillColor).toBe("currentColor");
    }
  });

  it("draws only the layers that are switched on, and always the flags", async () => {
    const { rerender } = render(scene({ showProjects: false, showMarinas: false }));
    await waitFor(() => expect(document.querySelectorAll(".flag-divicon").length).toBeGreaterThan(0));
    expect(circles).toHaveLength(0);

    rerender(scene({ showProjects: true, showMarinas: false }));
    await waitFor(() => expect(circles.length).toBe(1));
    expect(circles[0].pane).toBe(LAYER_PANES.projects);

    rerender(scene({ showProjects: true, showMarinas: true }));
    await waitFor(() => expect(circles.filter((options) => options.pane === LAYER_PANES.marinas)).toHaveLength(2));
    expect(document.querySelectorAll(".flag-divicon").length).toBeGreaterThan(0);
  });
});

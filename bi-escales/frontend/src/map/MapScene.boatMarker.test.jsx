import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import L from "leaflet";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { PRODUCTION_T0_ISO } from "../voyage/departureT0.js";
import { dedupeStopsByMilestone } from "../voyage/stopsForMap.js";
import { sampleAt, voyageFromRoute } from "../voyage/loadVoyage.js";
import { MapScene } from "./MapScene.jsx";

const here = dirname(fileURLToPath(import.meta.url));

function loadFixture() {
  const fc = JSON.parse(readFileSync(join(here, "../../public/route.geojson"), "utf8"));
  const voyage = voyageFromRoute(fc, PRODUCTION_T0_ISO);
  const sample = sampleAt(voyage.clock, new Date("2026-11-09T12:00:00.000Z"));
  const stops = dedupeStopsByMilestone(voyage.stops);
  const boat =
    sample && Number.isFinite(sample.lat)
      ? { lat: sample.lat, lon: sample.lon, bearing: sample.bearing || 0 }
      : null;
  return { voyage, sample, stops, boat };
}

describe("MapScene boat and stop markers", () => {
  const created = [];

  beforeEach(async () => {
    created.length = 0;
    await i18n.changeLanguage("en");
    const orig = L.marker.bind(L);
    vi.spyOn(L, "marker").mockImplementation((latlng, options) => {
      const marker = orig(latlng, options);
      created.push({ latlng, options, marker });
      return marker;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  function markerByMilestone(id) {
    return created.find((row) => row.options?.stopData?.milestoneId === id);
  }

  function boatMarker() {
    return created.find((row) => row.options?.pane === "boat");
  }

  async function renderScene(handlers = {}) {
    const { voyage, stops, boat } = loadFixture();
    const onSelectStop = handlers.onSelectStop ?? vi.fn();
    const onSelectBoat = handlers.onSelectBoat ?? vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <MapScene
          segments={voyage.segments}
          stops={stops}
          boat={boat}
          projects={{ type: "FeatureCollection", features: [] }}
          marinas={{ type: "FeatureCollection", features: [] }}
          showProjects={false}
          showMarinas={false}
          onSelectStop={onSelectStop}
          onSelectBoat={onSelectBoat}
          theme="dark"
        />
      </I18nextProvider>,
    );
    await waitFor(() => expect(created.length).toBeGreaterThan(2), { timeout: 4000 });
    return { onSelectStop, onSelectBoat, stops, boat };
  }

  it("routes La Rochelle marker clicks to the La Rochelle card", async () => {
    const { onSelectStop } = await renderScene();
    const laRochelle = markerByMilestone("dep-la-rochelle");
    expect(laRochelle).toBeTruthy();
    laRochelle.marker.fire("click", { target: laRochelle.marker });
    expect(onSelectStop).toHaveBeenCalledWith(
      expect.objectContaining({ milestoneId: "dep-la-rochelle", name: "La Rochelle" }),
    );
  });

  it("keeps boat clicks on onSelectBoat, not the La Rochelle stop handler", async () => {
    const { onSelectStop, onSelectBoat } = await renderScene();
    const boat = boatMarker();
    expect(boat).toBeTruthy();
    boat.marker.fire("click");
    expect(onSelectBoat).toHaveBeenCalledTimes(1);
    expect(onSelectStop).not.toHaveBeenCalled();
  });

  it.each([
    ["en", "Boat / catamaran"],
    ["fr", "Bateau / catamaran"],
  ])("exposes localized boat aria-label in %s", async (lang, label) => {
    await i18n.changeLanguage(lang);
    await renderScene({ onSelectBoat: vi.fn() });
    const boat = boatMarker();
    expect(boat.options.icon.options.html).toContain(`aria-label="${label}"`);
  });

  it.each([
    ["en", "Voyage stop: La Rochelle"],
    ["fr", "Escale : La Rochelle"],
  ])("exposes localized stop flag aria-label in %s", async (lang, label) => {
    await i18n.changeLanguage(lang);
    await renderScene();
    const laRochelle = markerByMilestone("dep-la-rochelle");
    expect(laRochelle).toBeTruthy();
    expect(laRochelle.options.icon.options.html).toContain(`aria-label="${label}"`);
    expect(laRochelle.options.icon.options.html).toContain('role="button"');
  });
});

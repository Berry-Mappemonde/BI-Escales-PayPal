import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
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
  return { voyage, stops, boat };
}

function laRochelleFlagControl() {
  return document.querySelector('[data-stop-marker][aria-label*="La Rochelle"]');
}

describe("MapScene stop flag keyboard (SITE-A11Y-2)", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("opens the stop sheet on Enter and Space from a focused flag", async () => {
    const user = userEvent.setup();
    const onSelectStop = vi.fn();
    const { voyage, stops, boat } = loadFixture();

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
          onSelectBoat={vi.fn()}
          theme="dark"
        />
      </I18nextProvider>,
    );

    await waitFor(() => expect(laRochelleFlagControl()).toBeTruthy(), { timeout: 4000 });

    const control = laRochelleFlagControl();
    control.focus();
    expect(document.activeElement).toBe(control);

    await user.keyboard("{Enter}");
    expect(onSelectStop).toHaveBeenCalledWith(
      expect.objectContaining({ milestoneId: "dep-la-rochelle", name: "La Rochelle" }),
    );

    onSelectStop.mockClear();
    await user.keyboard(" ");
    expect(onSelectStop).toHaveBeenCalledWith(
      expect.objectContaining({ milestoneId: "dep-la-rochelle", name: "La Rochelle" }),
    );
  });
});

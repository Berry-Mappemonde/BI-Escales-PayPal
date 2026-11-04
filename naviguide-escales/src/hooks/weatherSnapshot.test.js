import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  WEATHER_POLL_MS,
  WEATHER_REFRESH_MS,
  productHasData,
  satelliteBusy,
  weatherPending,
  weatherPollMs,
  pollWeatherUntil,
} from "./weatherSnapshot.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (name) => readFileSync(join(here, name), "utf8");

describe("weatherSnapshot", () => {
  it("treats pending without data as busy, ready products as present", () => {
    assert.equal(weatherPending({ status: "pending", refreshing: true }), true);
    assert.equal(satelliteBusy({ status: "pending", refreshing: true }), true);
    assert.equal(productHasData({ wind_speed_knots: 12.4 }, "wind"), true);
    assert.equal(productHasData({ status: "pending" }, "wind"), false);
    assert.equal(weatherPollMs({ status: "pending" }), WEATHER_POLL_MS);
    assert.equal(weatherPollMs({ status: "ready" }), WEATHER_REFRESH_MS);
    assert.equal(satelliteBusy({
      status: "pending",
      refreshing: true,
      wind: { status: "ready", wind_speed_knots: 11 },
    }), false);
  });

  it("polls until the snapshot is ready", async () => {
    let n = 0;
    const body = await pollWeatherUntil(
      async () => {
        n += 1;
        return n < 3 ? { status: "pending" } : { status: "ready", wind_speed_knots: 9 };
      },
      (row) => row.status === "ready",
      { timeoutMs: 2000, intervalMs: 10 },
    );
    assert.equal(body.status, "ready");
    assert.equal(n, 3);
  });

  it("is used by the satellite popup, route wind, expedition speed and ICI", () => {
    // The satellite popup lives in its own hook (App only mounts it).
    const app = read("useSatellitePopup.js");
    assert.match(read("../App.jsx"), /useSatellitePopup\(\)/);
    const profile = read("useRouteWindProfile.js");
    const speed = read("useExpeditionSpeed.js");
    const ici = read("useIciDossier.js");
    assert.match(app, /fetchWeatherComposite/);
    assert.match(app, /weatherPollMs/);
    assert.match(profile, /pollWeatherUntil/);
    assert.match(speed, /pollWeatherUntil/);
    assert.match(ici, /fetchWeatherForecast/);
    assert.match(ici, /WEATHER_POLL_MS/);
  });
});

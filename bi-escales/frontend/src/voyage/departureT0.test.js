import { describe, expect, it } from "vitest";
import { DEFAULT_T0_ISO } from "./voyageClock.js";
import { PRODUCTION_T0_ISO, resolveDepartureT0 } from "./departureT0.js";

describe("resolveDepartureT0", () => {
  it("fixe le 12 novembre 2026 en production", () => {
    expect(DEFAULT_T0_ISO).toBe("2026-11-12T08:00:00.000Z");
    expect(PRODUCTION_T0_ISO).toBe(DEFAULT_T0_ISO);
    expect(resolveDepartureT0(true, "2026-05-15T08:00:00.000Z")).toBe(PRODUCTION_T0_ISO);
  });

  it("garde le t0 de développement", () => {
    expect(resolveDepartureT0(false, "2026-05-15T08:00:00.000Z")).toBe("2026-05-15T08:00:00.000Z");
  });
});

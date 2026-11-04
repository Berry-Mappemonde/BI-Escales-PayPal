import { describe, expect, it, beforeEach, vi } from "vitest";
import { agGridLicenseKey, featureAgGridEnabled, featureAgStudioEnabled } from "../config/features";
import { loadTrackedPledgeIds, saveTrackedPledgeIds, trackPledgeId } from "../hooks/pledgeQueueStorage";

describe("featureAgGridEnabled", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
  });

  it("est désactivé par défaut", () => {
    expect(featureAgGridEnabled()).toBe(false);
  });

  it("accepte la valeur truthy explicite", () => {
    vi.stubEnv("VITE_ENABLE_AG_GRID", "true");
    expect(featureAgGridEnabled()).toBe(true);
  });
});

describe("featureAgStudioEnabled", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "0");
    vi.stubEnv("VITE_AG_GRID_LICENSE_KEY", "");
  });

  it("est désactivé par défaut", () => {
    expect(featureAgStudioEnabled()).toBe(false);
  });

  it("accepte la valeur truthy explicite", () => {
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "1");
    expect(featureAgStudioEnabled()).toBe(true);
  });

  it("ne fournit pas de clé de licence tant qu’elle est vide", () => {
    expect(agGridLicenseKey()).toBeUndefined();
    vi.stubEnv("VITE_AG_GRID_LICENSE_KEY", "  ");
    expect(agGridLicenseKey()).toBeUndefined();
  });
});

describe("pledgeQueueStorage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("persiste les identifiants en session", () => {
    trackPledgeId("abc");
    expect(loadTrackedPledgeIds()).toEqual(["abc"]);
    saveTrackedPledgeIds(["x", "y"]);
    expect(loadTrackedPledgeIds()).toEqual(["x", "y"]);
  });
});

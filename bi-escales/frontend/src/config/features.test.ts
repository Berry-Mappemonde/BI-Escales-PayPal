import { describe, expect, it, beforeEach, vi } from "vitest";
import { featureAgGridEnabled } from "../config/features";
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

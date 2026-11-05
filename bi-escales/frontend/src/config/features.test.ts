import { describe, expect, it, beforeEach, vi } from "vitest";
import { readPaypalReturn, readVaultReturn } from "../api/escales";
import {
  agGridLicenseKey,
  agStudioLlmEndpoint,
  featureAgGridEnabled,
  featureAgStudioEnabled,
} from "../config/features";
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
    vi.unstubAllEnvs();
  });

  it("est désactivé si la variable est absente, vide ou à 0", () => {
    expect(featureAgStudioEnabled()).toBe(false);
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "");
    expect(featureAgStudioEnabled()).toBe(false);
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "0");
    expect(featureAgStudioEnabled()).toBe(false);
  });

  it("accepte la valeur truthy explicite", () => {
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "1");
    expect(featureAgStudioEnabled()).toBe(true);
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", " TRUE ");
    expect(featureAgStudioEnabled()).toBe(true);
  });
});

describe("variables AG Studio", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
  });

  it("traite une licence ou un proxy vide comme absent", () => {
    vi.stubEnv("VITE_AG_GRID_LICENSE_KEY", "  ");
    vi.stubEnv("VITE_AG_STUDIO_LLM_ENDPOINT", "");
    expect(agGridLicenseKey()).toBeUndefined();
    expect(agStudioLlmEndpoint()).toBeUndefined();
  });

  it("retire les espaces autour des valeurs", () => {
    vi.stubEnv("VITE_AG_GRID_LICENSE_KEY", " test-licence ");
    vi.stubEnv("VITE_AG_STUDIO_LLM_ENDPOINT", " http://localhost:9000/llm ");
    expect(agGridLicenseKey()).toBe("test-licence");
    expect(agStudioLlmEndpoint()).toBe("http://localhost:9000/llm");
  });
});

describe("readPaypalReturn", () => {
  it("ne lit un retour que lorsque PayPal renvoie la page", () => {
    expect(readPaypalReturn("")).toBeNull();
    expect(readPaypalReturn("?token=ORDER1")).toBeNull();
    expect(readPaypalReturn("?paypal=return&pledge_id=abc")).toEqual({ action: "return", pledgeId: "abc" });
    expect(readPaypalReturn("?paypal=cancel&pledge_id=abc")).toEqual({ action: "cancel", pledgeId: "abc" });
  });
});

describe("readVaultReturn", () => {
  it("lit le retour Vault PayPal", () => {
    expect(readVaultReturn("?vault=return&pledge_id=v1&approval_token_id=tok1")).toEqual({
      action: "return",
      pledgeId: "v1",
      approvalTokenId: "tok1",
    });
    expect(readVaultReturn("?vault=cancel&pledge_id=v1")).toEqual({ action: "cancel", pledgeId: "v1" });
    expect(readVaultReturn("?paypal=return&pledge_id=abc")).toBeNull();
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

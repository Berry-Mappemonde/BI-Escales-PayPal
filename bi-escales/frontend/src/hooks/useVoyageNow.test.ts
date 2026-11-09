import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as escalesApi from "../api/escales";
import { useVoyageNow, voyageNowFromClock } from "./useVoyageNow";

describe("voyageNowFromClock", () => {
  it("prefers now over start", () => {
    const d = voyageNowFromClock({
      start: "2026-11-12T08:00:00.000Z",
      now: "2026-11-12T12:00:00.000Z",
    });
    expect(d.toISOString()).toBe("2026-11-12T12:00:00.000Z");
  });

  it("falls back to start when now is absent", () => {
    const d = voyageNowFromClock({ start: "2026-11-12T08:00:00.000Z" });
    expect(d.toISOString()).toBe("2026-11-12T08:00:00.000Z");
  });
});

describe("useVoyageNow", () => {
  beforeEach(() => {
    vi.spyOn(escalesApi, "fetchClock").mockResolvedValue({
      start: "2026-11-12T08:00:00.000Z",
      now: "2026-11-12T08:00:00.000Z",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the simulated instant from the API instead of wall time", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2030-01-01T00:00:00Z").getTime());
    const { result } = renderHook(() => useVoyageNow());
    await waitFor(() => {
      expect(result.current.toISOString()).toBe("2026-11-12T08:00:00.000Z");
    });
    expect(escalesApi.fetchClock).toHaveBeenCalled();
  });
});

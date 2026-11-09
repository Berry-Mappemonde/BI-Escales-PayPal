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
    expect(d?.toISOString()).toBe("2026-11-12T12:00:00.000Z");
  });

  it("falls back to start when now is absent", () => {
    const d = voyageNowFromClock({ start: "2026-11-12T08:00:00.000Z" });
    expect(d?.toISOString()).toBe("2026-11-12T08:00:00.000Z");
  });

  it("returns null when the clock body has no usable instant", () => {
    expect(voyageNowFromClock({})).toBeNull();
    expect(voyageNowFromClock(null)).toBeNull();
    expect(voyageNowFromClock({ now: "not-a-date" })).toBeNull();
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

  it("starts with null instead of wall time before the clock API answers", async () => {
    const wall = new Date("2030-06-15T12:00:00.000Z");
    vi.spyOn(Date, "now").mockReturnValue(wall.getTime());

    let resolveClock!: (value: { now: string; start: string }) => void;
    const pending = new Promise<{ now: string; start: string }>((resolve) => {
      resolveClock = resolve;
    });
    vi.spyOn(escalesApi, "fetchClock").mockReturnValue(pending);

    const { result } = renderHook(() => useVoyageNow());
    expect(result.current).toBeNull();
    expect(result.current?.toISOString()).not.toBe(wall.toISOString());

    resolveClock({
      start: "2026-11-12T08:00:00.000Z",
      now: "2026-11-12T08:00:00.000Z",
    });
    await waitFor(() => {
      expect(result.current?.toISOString()).toBe("2026-11-12T08:00:00.000Z");
    });
  });

  it("loads the simulated instant from the API instead of wall time", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2030-01-01T00:00:00Z").getTime());
    const { result } = renderHook(() => useVoyageNow());
    await waitFor(() => {
      expect(result.current?.toISOString()).toBe("2026-11-12T08:00:00.000Z");
    });
    expect(escalesApi.fetchClock).toHaveBeenCalled();
  });

  it("keeps null when the clock call fails (no wall-clock fallback)", async () => {
    vi.spyOn(escalesApi, "fetchClock").mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useVoyageNow());
    await waitFor(() => expect(escalesApi.fetchClock).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});

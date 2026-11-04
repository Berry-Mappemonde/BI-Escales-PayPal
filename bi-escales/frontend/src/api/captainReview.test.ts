import { afterEach, describe, expect, it, vi } from "vitest";
import { captainReview } from "./escales";

describe("captainReview", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the app language as ?lang= on the review route", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ proposal: "wait" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await captainReview("dep-la-rochelle", "admin-key", "fr");

    const calledUrl = String(fetchMock.mock.calls[0]?.[0] ?? "");
    expect(calledUrl).toContain("/api/escales/captain/review/dep-la-rochelle");
    expect(calledUrl).toContain("lang=fr");
  });
});

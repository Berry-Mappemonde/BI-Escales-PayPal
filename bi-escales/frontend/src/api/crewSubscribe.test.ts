import { describe, expect, it, vi } from "vitest";
import { crewSubscriptionPageUrls, readCrewSubscribeReturn } from "./escales";

describe("crew subscription return URLs", () => {
  it("readCrewSubscribeReturn parses ?sub= query params", () => {
    expect(readCrewSubscribeReturn("?sub=return&subscription_id=I-1", "")).toEqual({
      action: "return",
      subscriptionId: "I-1",
    });
    expect(readCrewSubscribeReturn("?sub=cancel", "")).toEqual({ action: "cancel" });
  });

  it("readCrewSubscribeReturn parses legacy hash fragments", () => {
    expect(readCrewSubscribeReturn("", "#crew-subscribe=return")).toEqual({ action: "return" });
    expect(readCrewSubscribeReturn("", "#crew-subscribe=cancel")).toEqual({ action: "cancel" });
  });

  it("crewSubscriptionPageUrls uses ?sub= on the current page", () => {
    vi.stubGlobal("location", {
      origin: "https://app.test",
      pathname: "/escales/",
    });
    expect(crewSubscriptionPageUrls()).toEqual({
      return_url: "https://app.test/escales/?sub=return",
      cancel_url: "https://app.test/escales/?sub=cancel",
    });
  });
});

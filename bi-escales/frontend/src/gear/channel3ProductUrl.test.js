import { describe, expect, it } from "vitest";
import {
  gearPageHref,
  isAbsoluteHttpsUrl,
  isChannel3HomepageUrl,
  normalizeChannel3ProductUrl,
} from "./channel3ProductUrl";

describe("channel3ProductUrl", () => {
  it("detects the Channel3 marketing homepage", () => {
    expect(isChannel3HomepageUrl("https://trychannel3.com/")).toBe(true);
    expect(isChannel3HomepageUrl("https://buy.trychannel3.com/x")).toBe(false);
    expect(isChannel3HomepageUrl("http://trychannel3.com/")).toBe(false);
  });

  it("never returns homepage URLs for gear Page links", () => {
    const props = {
      project_kind: "gear_project",
      fully_funded: true,
      channel3_buy_url: "https://trychannel3.com/",
    };
    expect(gearPageHref(props)).toBe("");
    const buy = "https://buy.trychannel3.com/gear-item";
    expect(gearPageHref({ ...props, channel3_buy_url: buy })).toBe(buy);
    expect(normalizeChannel3ProductUrl("https://trychannel3.com/")).toBe("");
  });

  describe("HTTPS-only via URL parser (kills scheme-check mutations)", () => {
    it.each([
      ["javascript:alert(1)", false, ""],
      ["http://buy.trychannel3.com/x", false, ""],
      ["data:text/html,hi", false, ""],
      ["/relative/path", false, ""],
      ["buy.trychannel3.com/item", false, ""],
      ["", false, ""],
      ["https://buy.trychannel3.com/safe", true, "https://buy.trychannel3.com/safe"],
    ])("url %j → isAbsoluteHttps=%s normalize=%j", (input, httpsOk, normalized) => {
      expect(isAbsoluteHttpsUrl(input)).toBe(httpsOk);
      expect(normalizeChannel3ProductUrl(input)).toBe(normalized);
    });

    it("rejects strings that only look like https via prefix, not parser", () => {
      expect(isAbsoluteHttpsUrl("https//buy.example/item")).toBe(false);
      expect(normalizeChannel3ProductUrl("https//buy.example/item")).toBe("");
    });
  });

  describe("gearPageHref blocks unsafe schemes when fully funded", () => {
    const base = { project_kind: "gear_project", fully_funded: true };

    it.each([
      ["javascript:alert(1)"],
      ["http://buy.trychannel3.com/x"],
    ])("no Page link for %s", (unsafeUrl) => {
      expect(gearPageHref({ ...base, channel3_buy_url: unsafeUrl })).toBe("");
      expect(gearPageHref({ ...base, url: unsafeUrl })).toBe("");
    });
  });
});

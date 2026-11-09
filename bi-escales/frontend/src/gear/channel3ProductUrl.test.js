import { describe, expect, it } from "vitest";
import { gearPageHref, isChannel3HomepageUrl, normalizeChannel3ProductUrl } from "./channel3ProductUrl";

describe("channel3ProductUrl", () => {
  it("detects the Channel3 marketing homepage", () => {
    expect(isChannel3HomepageUrl("https://trychannel3.com/")).toBe(true);
    expect(isChannel3HomepageUrl("https://buy.trychannel3.com/x")).toBe(false);
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
});

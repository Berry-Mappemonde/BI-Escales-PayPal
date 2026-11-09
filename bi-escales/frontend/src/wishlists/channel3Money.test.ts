import { describe, expect, it } from "vitest";
import { formatMinorAsMajor, parseWishlistPledgeAmount } from "./channel3Money";

describe("channel3Money", () => {
  it("parses JPY as whole units", () => {
    expect(parseWishlistPledgeAmount("500", "JPY")).toEqual({ kind: "ok", apiAmount: "500" });
    expect(parseWishlistPledgeAmount("1.5", "JPY").kind).toBe("invalid");
  });

  it("formats JPY without decimal fraction digits", () => {
    const label = formatMinorAsMajor(1500, "JPY", "en");
    expect(label).toMatch(/1,?500/);
  });
});

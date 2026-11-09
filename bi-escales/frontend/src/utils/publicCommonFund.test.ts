import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { publicCommonFundMessage } from "./publicCommonFund";

describe("publicCommonFundMessage", () => {
  it("shows first-giver copy when balance is zero", () => {
    const t = i18n.getFixedT("fr");
    expect(
      publicCommonFundMessage({ balance_eur: 0, currency: "EUR", income_eur: 0, spending_eur: 0 }, "fr", t),
    ).toBe("Fonds communautaire · Soyez le premier à donner");
  });

  it("keeps formatted balance when non-zero", () => {
    const t = i18n.getFixedT("en");
    const line = publicCommonFundMessage(
      { balance_eur: 12.5, currency: "EUR", income_eur: 12.5, spending_eur: 0 },
      "en",
      t,
    );
    expect(line).toContain("Community fund ·");
    expect(line).not.toMatch(/first to give/i);
  });
});

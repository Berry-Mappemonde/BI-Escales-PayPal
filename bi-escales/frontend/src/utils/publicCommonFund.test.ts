import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { publicCommonFundMessage } from "./publicCommonFund";

describe("publicCommonFundMessage", () => {
  it("shows first-giver copy when balance is zero", () => {
    const t = i18n.getFixedT("fr");
    expect(
      publicCommonFundMessage(
        {
          milestone_id: "common",
          balance_eur: "0.00",
          currency: "EUR",
          income_eur: "0.00",
          spending_eur: "0.00",
        },
        "fr",
        t,
      ),
    ).toBe("Fonds communautaire · Soyez le premier à donner");
  });

  it("keeps formatted balance when non-zero", () => {
    const t = i18n.getFixedT("en");
    const line = publicCommonFundMessage(
      {
        milestone_id: "common",
        balance_eur: "12.50",
        currency: "EUR",
        income_eur: "12.50",
        spending_eur: "0.00",
      },
      "en",
      t,
    );
    expect(line).toContain("Community fund ·");
    expect(line).not.toMatch(/first to give/i);
  });
});

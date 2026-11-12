import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import type { FundView } from "../api/types";
import { formatCommonFundBalance, publicCommonFundMessage } from "./publicCommonFund";

const fund = (balance: string): FundView => ({ balance_eur: balance, currency: "EUR" }) as FundView;
const plain = (text: string) => text.replace(/\s/g, " ");

describe("publicCommonFundMessage", () => {
  it("invites the first gift while the fund is empty", () => {
    expect(publicCommonFundMessage(fund("0.00"), "en", i18n.getFixedT("en"))).toBe(
      "Common fund · Be the first to give",
    );
    expect(publicCommonFundMessage(fund("0.00"), "fr", i18n.getFixedT("fr"))).toBe(
      "Caisse commune · Soyez le premier à donner",
    );
  });

  it("shows the balance as soon as there is one", () => {
    expect(plain(publicCommonFundMessage(fund("12.50"), "en", i18n.getFixedT("en")))).toBe("Common fund · €12.50");
    expect(plain(publicCommonFundMessage(fund("12.50"), "fr", i18n.getFixedT("fr")))).toBe("Caisse commune · 12,50 €");
  });

  it("shows a balance it cannot read as it came, never as an empty fund", () => {
    expect(publicCommonFundMessage(fund("n/a"), "en", i18n.getFixedT("en"))).toBe("Common fund · n/a EUR");
    expect(formatCommonFundBalance(fund("n/a"), "en")).toBe("n/a EUR");
  });
});

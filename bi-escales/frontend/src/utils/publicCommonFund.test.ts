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

  // Real shape of GET /api/escales/common-fund/fund on test2 (12 Nov 2026), before any gift.
  const realEmpty: FundView = {
    milestone_id: "fonds-commun",
    currency: "EUR",
    income_eur: "0.00",
    captured_eur: "0.00",
    authorized_eur: "0.00",
    spending_eur: "0.00",
    refunded_eur: "0.00",
    balance_eur: "0.00",
    overdrawn: false,
    received_net_eur: "0.00",
  };

  it("invites the first gift on the real empty fund", () => {
    expect(publicCommonFundMessage(realEmpty, "en", i18n.getFixedT("en"))).toBe("Common fund · Be the first to give");
  });

  it("never invites the first gift once gifts were received, even at a zero balance", () => {
    const used = { ...realEmpty, income_eur: "25.00", captured_eur: "25.00", received_net_eur: "25.00", spending_eur: "25.00" };
    expect(plain(publicCommonFundMessage(used, "en", i18n.getFixedT("en")))).toBe(
      "Common fund · €0.00 · €25.00 received, all put to use",
    );
    expect(plain(publicCommonFundMessage(used, "fr", i18n.getFixedT("fr")))).toBe(
      "Caisse commune · 0,00 € · 25,00 € reçus, entièrement utilisés",
    );
  });

  it("shows the zero balance, not the invitation, when a gift is only authorised or was refunded", () => {
    for (const activity of [{ authorized_eur: "10.00" }, { refunded_eur: "10.00", received_net_eur: "0.00" }]) {
      expect(plain(publicCommonFundMessage({ ...realEmpty, ...activity }, "en", i18n.getFixedT("en")))).toBe(
        "Common fund · €0.00",
      );
    }
  });

  it("does not call the fund empty when an amount cannot be read", () => {
    expect(plain(publicCommonFundMessage({ ...realEmpty, income_eur: "n/a" }, "en", i18n.getFixedT("en")))).toBe(
      "Common fund · €0.00",
    );
  });

  it("shows a balance it cannot read as it came, never as an empty fund", () => {
    expect(publicCommonFundMessage(fund("n/a"), "en", i18n.getFixedT("en"))).toBe("Common fund · n/a EUR");
    expect(formatCommonFundBalance(fund("n/a"), "en")).toBe("n/a EUR");
  });
});

import { describe, expect, it } from "vitest";
import {
  amountFromSuggestedPledge,
  catalogExactPrice,
  defaultAmountForKind,
  pledgeOrderAmount,
} from "./stopPledgeAmount.js";

const catalog = {
  prices: [
    { kind: "berth", amount_eur: "30.00", simulated: true },
    { kind: "cabin_leg", amount_eur: "80.00", simulated: true },
    { kind: "night", amount_eur: "60.00", simulated: true },
    { kind: "project_pledge", free_amount: true },
  ],
};

describe("stopPledgeAmount", () => {
  it("aligne berth sur le catalogue alors que l'état affichait 20 milles", () => {
    expect(pledgeOrderAmount("berth", "20.00", catalog)).toBe("30.00");
    expect(defaultAmountForKind("berth", catalog)).toBe("30.00");
  });

  it("aligne cabin_leg sur 80.00 même si le champ vaut encore 20.00", () => {
    expect(pledgeOrderAmount("cabin_leg", "20.00", catalog)).toBe("80.00");
  });

  it("laisse le montant libre pour les milles", () => {
    expect(pledgeOrderAmount("mile", "20.00", catalog)).toBe("20.00");
    expect(catalogExactPrice("mile", catalog)).toBeNull();
  });

  it("normalise une suggestion capitaine avec tarif fixe", () => {
    expect(
      amountFromSuggestedPledge({ kind: "cabin_leg", amount_eur: "20.00" }, catalog),
    ).toBe("80.00");
    expect(
      amountFromSuggestedPledge({ kind: "berth", amount_eur: "20.00" }, catalog),
    ).toBe("30.00");
  });
});

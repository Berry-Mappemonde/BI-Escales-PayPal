import { describe, expect, it } from "vitest";
import {
  isBelowProjectPledgeMinimum,
  normalizeEuroAmountForApi,
} from "./projectPledgeAmount.js";

describe("projectPledgeAmount", () => {
  it("accepte la virgule décimale", () => {
    expect(normalizeEuroAmountForApi("1,50")).toBe("1.50");
    expect(isBelowProjectPledgeMinimum("1,50")).toBe(false);
  });

  it("signale vide, zéro et sous le minimum", () => {
    expect(isBelowProjectPledgeMinimum("")).toBe(true);
    expect(isBelowProjectPledgeMinimum("0")).toBe(true);
    expect(isBelowProjectPledgeMinimum("0,50")).toBe(true);
  });
});

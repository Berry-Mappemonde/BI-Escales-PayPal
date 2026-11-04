import { describe, expect, it } from "vitest";
import { parseProjectPledgeAmount } from "./projectPledgeAmount.js";

describe("parseProjectPledgeAmount", () => {
  it("accepte la virgule décimale simple", () => {
    expect(parseProjectPledgeAmount("1,50")).toEqual({ kind: "ok", apiAmount: "1.50" });
  });

  it("refuse plus de deux décimales et les séparateurs mixtes", () => {
    expect(parseProjectPledgeAmount("1,005").kind).toBe("invalid");
    expect(parseProjectPledgeAmount("1.005").kind).toBe("invalid");
    expect(parseProjectPledgeAmount("1.234,56").kind).toBe("invalid");
  });

  it("distingue format invalide et sous-minimum", () => {
    expect(parseProjectPledgeAmount("0,50").kind).toBe("below_min");
    expect(parseProjectPledgeAmount("").kind).toBe("empty");
    expect(parseProjectPledgeAmount("abc").kind).toBe("invalid");
  });
});

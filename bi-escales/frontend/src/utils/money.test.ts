import { describe, expect, it } from "vitest";
import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("writes French and English amounts", () => {
    expect(formatMoney("120", "fr")).toBe("120,00 €");
    expect(formatMoney(120, "en")).toBe("120.00 EUR");
  });
});

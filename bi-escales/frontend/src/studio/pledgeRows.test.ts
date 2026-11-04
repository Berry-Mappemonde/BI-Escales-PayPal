import { describe, expect, it } from "vitest";
import { nextDataAgentAction, nextTreasurerAction } from "./agentPlan";
import { toPledgeStudioRows, totalsFromStudioRows } from "./pledgeRows";

describe("toPledgeStudioRows", () => {
  it("convertit le montant et laisse le contributeur vide", () => {
    const [row] = toPledgeStudioRows([
      {
        id: "p1",
        status: "authorized",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "12.50",
        description: "eau",
        milestone_id: "dep-mayotte",
      },
    ]);
    expect(row).toMatchObject({
      id: "p1",
      status: "authorized",
      amount_eur: 12.5,
      contributor: "",
      milestone_id: "dep-mayotte",
    });
  });
});

describe("totalsFromStudioRows", () => {
  it("somme les montants quel que soit le préfixe de colonne", () => {
    const totals = totalsFromStudioRows([
      { "pledges.status": "authorized", "pledges.amount_eur": 10 },
      { status: "authorized", amount_eur: "2.5" },
      { status: "captured", "sum(amount_eur)": 4 },
      { status: "voided", amount: 1 },
    ]);
    expect(totals).toEqual({ authorized: 12.5, captured: 4, voided: 1 });
  });
});

describe("nextTreasurerAction", () => {
  it("délègue d’abord à l’agent data de Studio", () => {
    expect(nextTreasurerAction("totaux", 0)).toEqual({
      kind: "delegate-data",
      instructions: "totaux",
    });
  });

  it("ajoute la jauge seulement si on le demande, puis répond", () => {
    expect(nextTreasurerAction("Ajoute la jauge", 1).kind).toBe("add-validation-widget");
    expect(nextTreasurerAction("Ajoute la jauge", 2).kind).toBe("reply");
    expect(nextTreasurerAction("Quels totaux ?", 1).kind).toBe("reply");
  });
});

describe("nextDataAgentAction", () => {
  it("lit le schéma puis clôt la délégation", () => {
    expect(nextDataAgentAction(0, "").kind).toBe("view-schema");
    expect(nextDataAgentAction(1, "pledges.amount_eur", "en").summary).toContain("Human validation");
    expect(nextDataAgentAction(1, "pledges.amount_eur", "fr").summary).toContain("validation humaine");
  });
});

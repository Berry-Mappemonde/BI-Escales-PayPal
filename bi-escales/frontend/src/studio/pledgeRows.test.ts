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

  it("déduit les remboursements du net sans descendre sous zéro", () => {
    const base = { intent: "CAPTURE", currency: "EUR", description: "eau", milestone_id: "m1" };
    const rows = toPledgeStudioRows([
      { ...base, id: "p1", status: "captured", amount_eur: "30.00" },
      { ...base, id: "p2", status: "partially_refunded", amount_eur: "30.00", refunded_amount_eur: "10.10" },
      { ...base, id: "p3", status: "refunded", amount_eur: "30.00", refunded_amount_eur: "30.00" },
      { ...base, id: "p4", status: "refunded", amount_eur: "30.00", refunded_amount_eur: "31.00" },
    ]);
    expect(rows.map((row) => row.net_eur)).toEqual([30, 19.9, 0, 0]);
    expect(rows.map((row) => row.amount_eur)).toEqual([30, 30, 30, 30]);
  });
});

describe("totalsFromStudioRows", () => {
  it("somme les montants quel que soit le préfixe de colonne", () => {
    const totals = totalsFromStudioRows([
      { "pledges.status": "authorized", "pledges.net_eur": 10 },
      { status: "authorized", net_eur: "2.5" },
      { status: "captured", "sum(net_eur)": 4 },
      { status: "voided", amount: 1 },
    ]);
    expect(totals).toEqual({ held: 12.5, saved: 0, captured: 4, released: 1 });
  });

  it("garde les promesses enregistrées hors du total retenu", () => {
    const totals = totalsFromStudioRows([
      { status: "authorized", net_eur: 10 },
      { status: "vaulted", net_eur: 25 },
    ]);
    expect(totals).toEqual({ held: 10, saved: 25, captured: 0, released: 0 });
  });

  it("compte l’encaissé net : partiel inclus, remboursement total à zéro", () => {
    const totals = totalsFromStudioRows([
      { status: "captured", net_eur: 30 },
      { status: "partially_refunded", net_eur: 19.9 },
      { status: "refunded", net_eur: 0 },
      { status: "refunded", amount_eur: 30 },
    ]);
    expect(totals.captured).toBeCloseTo(49.9);
  });

  it("préfère le net au montant brut quand la ligne porte les deux", () => {
    const totals = totalsFromStudioRows([{ status: "partially_refunded", amount_eur: 30, net_eur: 20 }]);
    expect(totals.captured).toBe(20);
  });

  it("ignore les statuts sans total", () => {
    const rows = ["created", "pending", "capture_failed", "charge_failed", "token_delete_pending"].map(
      (status) => ({ status, net_eur: 5 }),
    );
    expect(totalsFromStudioRows(rows)).toEqual({ held: 0, saved: 0, captured: 0, released: 0 });
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
    const enAction = nextDataAgentAction(1, "pledges.amount_eur", "en");
    const frAction = nextDataAgentAction(1, "pledges.amount_eur", "fr");
    expect(enAction.kind).toBe("complete");
    expect(frAction.kind).toBe("complete");
    if (enAction.kind === "complete") {
      expect(enAction.summary).toContain("Human validation");
    }
    if (frAction.kind === "complete") {
      expect(frAction.summary).toContain("validation humaine");
    }
  });
});

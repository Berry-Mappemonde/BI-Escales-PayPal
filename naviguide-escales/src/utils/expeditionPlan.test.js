import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { normalizeExpeditionPlan } from "./expeditionPlan.js";

describe("normalizeExpeditionPlan", () => {
  it("conserve un briefing_title optionnel fourni par l’orchestrateur", () => {
    assert.deepEqual(
      normalizeExpeditionPlan({
        executive_briefing: "  Mer formée au large.  ",
        briefing_title: "  Passage des Açores  ",
      }),
      {
        executive_briefing: "Mer formée au large.",
        briefing_title: "Passage des Açores",
      },
    );
  });

  it("n’invente pas de titre lorsque le contrat ne le contient pas", () => {
    assert.deepEqual(
      normalizeExpeditionPlan({ executive_briefing: "Briefing sans titre." }),
      { executive_briefing: "Briefing sans titre." },
    );
  });
});

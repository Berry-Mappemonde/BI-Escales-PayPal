import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { analyze, analyzeFolded, formatReport } from "../../scripts/redites.mjs";
import fr from "./fr.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("scripts/redites.mjs", () => {
  it("liste les valeurs identiques et les groupes de ≥ 2 mots, triés par fréquence", () => {
    const report = analyze(fr);
    assert.ok(report.identical.length >= 1, "au moins une valeur partagée");
    const hide = report.identical.find((row) => row.value === "Masquer le panneau");
    assert.ok(hide, "« Masquer le panneau » sous plusieurs clés");
    assert.ok(hide.n >= 2);
    assert.ok(hide.keys.includes("hideSidebar"));
    assert.ok(report.groups.length >= 1, "au moins un groupe de mots partagé");
    const first = report.groups[0];
    assert.ok(first.n >= 2);
    assert.ok(first.group.split(" ").length >= 2);
    for (let i = 1; i < report.groups.length; i += 1) {
      assert.ok(report.groups[i - 1].n >= report.groups[i].n, "groupes triés par fréquence");
    }
    const text = formatReport(report);
    assert.match(text, /Valeurs identiques/);
    assert.match(text, /Groupes de ≥ 2 mots/);
  });

  it("compte les doublons <summary> / contenu déplié", () => {
    const fixture = `
      const PROFILE_KEY = { cruise: "skipperProfileCruise" };
      const summary = [t(PROFILE_KEY[profile]), isSuivre ? \`\${horizonH} h\` : null].join(" · ");
      <details>
        <summary>{t("advancedSettings")} {summary}</summary>
        <div>{t(PROFILE_KEY[p])} {orders.budget.hours} h</div>
      </details>
    `;
    const hits = analyzeFolded(fixture, fr);
    assert.ok(hits.length >= 1, "redite profil/budget détectée");
    const dups = hits.flatMap((h) => h.dups);
    assert.ok(dups.includes("Croisière") || dups.includes("HORIZON_H"), `dups=${dups.join(",")}`);

    const panel = readFileSync(join(here, "../components/SkipperOrdersPanel.jsx"), "utf8");
    const live = analyzeFolded(panel, fr);
    const liveDups = live.flatMap((h) => h.dups);
    assert.equal(liveDups.includes("Croisière"), false, "plus de Croisière dans le summary");
    assert.equal(liveDups.includes("HORIZON_H"), false, "plus d'horizon dans le summary");
  });
});

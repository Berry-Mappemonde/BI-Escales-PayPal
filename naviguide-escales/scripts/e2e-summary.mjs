#!/usr/bin/env node
// Résumé d'étape GitHub : N specs, rouges nommés, poste (skipped CI).
import { readFileSync } from "node:fs";

const path = process.argv[2] || "test-results/e2e.json";
let report;
try {
  report = JSON.parse(readFileSync(path, "utf8"));
} catch {
  console.log("## Recette automatique Playwright\n\nrapport JSON absent.");
  process.exit(0);
}

const tests = [];
for (const suite of report.suites || []) walk(suite);

function walk(suite) {
  for (const spec of suite.specs || []) {
    for (const t of spec.tests || []) {
      const result = (t.results || [])[0] || {};
      const status = t.status || result.status || "unknown";
      const annotations = (t.annotations || []).map((a) => a.type || a.description || "").join(" ");
      // Réserves : ce qu'un spec VERT n'a pas pu vérifier (surface absente, API muette…) — un vert avec
      // réserve n'a rien prouvé sur ce point ; s'il revient à chaque run, la surface a disparu (spec obsolète).
      const allNotes = (t.annotations || []).filter((a) => a.type !== "skip");
      const isPoste = (a) => /^poste$/i.test(a.type || "");
      const isMesure = (a) => /^mesure$/i.test(a.type || "") || /^(zoom-ms|zoom-ms-avant)$/i.test(a.type || "");
      const isSansApi = (a) => /^sans API$/i.test(a.type || "");
      const reserves = allNotes
        .filter((a) => !isPoste(a) && !isMesure(a) && !isSansApi(a))
        .map((a) => `${a.type || "réserve"}${a.description ? ` : ${a.description}` : ""}`);
      const postes = allNotes
        .filter(isPoste)
        .map((a) => `${a.type}${a.description ? ` : ${a.description}` : ""}`);
      const mesures = allNotes
        .filter(isMesure)
        .map((a) => `${a.type}${a.description ? ` : ${a.description}` : ""}`);
      tests.push({
        title: spec.title,
        file: spec.file || suite.file || "",
        status,
        annotations,
        reserves,
        postes,
        mesures,
      });
    }
  }
  for (const child of suite.suites || []) walk(child);
}

const failed = tests.filter((t) => t.status === "unexpected" || t.status === "failed");
const skipped = tests.filter((t) => t.status === "skipped");
const poste = skipped.filter((t) => /poste/i.test(t.annotations));
const passed = tests.filter((t) => t.status === "expected" || t.status === "passed");

console.log("## Recette automatique Playwright");
console.log("");
console.log(`**${failed.length} spec rouge**, ${tests.length} specs, ${poste.length} poste, ${skipped.length} ignorés, ${passed.length} verts.`);
console.log("");
if (failed.length) {
  console.log("### Specs rouges");
  for (const t of failed) console.log(`- \`${t.file}\` — ${t.title}`);
} else {
  console.log("0 spec rouge.");
}
if (poste.length) {
  console.log("");
  console.log("### Specs poste (ignorés en CI)");
  for (const t of poste) console.log(`- \`${t.file}\` — ${t.title}`);
}
const otherSkipped = skipped.filter((t) => !poste.includes(t));
if (otherSkipped.length) {
  console.log("");
  console.log("### Specs ignorés (surface disparue — décision à prendre)");
  for (const t of otherSkipped) console.log(`- \`${t.file}\` — ${t.title}${t.annotations ? ` — ${t.annotations}` : ""}`);
}
const withReserve = passed.filter((t) => t.reserves.length);
if (withReserve.length) {
  console.log("");
  console.log(`### Verts avec réserve (${withReserve.length}) — vérifié en partie seulement`);
  for (const t of withReserve) for (const r of t.reserves) console.log(`- \`${t.file}\` — ${r}`);
} else {
  console.log("");
  console.log("### Verts avec réserve (0) — vérifié en partie seulement");
  console.log("0. Les chemins poste / mesure sont rangés à part.");
}
const withPoste = passed.filter((t) => (t.postes || []).length);
if (withPoste.length) {
  console.log("");
  console.log(`### Poste (${withPoste.length}) — attendu hors CI (atlas, hindcast, isochrone, LLM)`);
  for (const t of withPoste) for (const r of t.postes) console.log(`- \`${t.file}\` — ${r}`);
}
const withMesure = passed.filter((t) => (t.mesures || []).length);
if (withMesure.length) {
  console.log("");
  console.log(`### Mesure (${withMesure.length}) — perf, pas une réserve`);
  for (const t of withMesure) for (const r of t.mesures) console.log(`- \`${t.file}\` — ${r}`);
}

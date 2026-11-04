#!/usr/bin/env node
/**
 * Redites i18n (fr.js).
 * Node, sans dépendance : groupes de ≥ 2 mots (hors mots vides) présents
 * dans ≥ 2 valeurs, et valeurs identiques sous deux clés. Tri par fréquence.
 * Doublons entre un <summary> replié et le contenu déplié.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const STOP = new Set([
  "le", "la", "de", "du", "des", "et", "à", "en", "un", "une", "sur", "par", "au", "aux", "pour",
]);

const here = dirname(fileURLToPath(import.meta.url));
const frPath = join(here, "../src/i18n/fr.js");
const { default: fr } = await import(pathToFileURL(frPath).href);

function wordsOf(value) {
  return String(value)
    .normalize("NFC")
    .toLowerCase()
    .match(/[a-zàâäéèêëïîôùûüçœæ0-9’']+/gi) || [];
}

function contentWords(value) {
  return wordsOf(value).filter((w) => !STOP.has(w.replace(/’/g, "'")));
}

function ngrams(tokens, min = 2) {
  const out = [];
  for (let n = min; n <= tokens.length; n += 1) {
    for (let i = 0; i + n <= tokens.length; i += 1) {
      out.push(tokens.slice(i, i + n).join(" "));
    }
  }
  return out;
}

export function analyze(dict) {
  const entries = Object.entries(dict).filter(([, v]) => typeof v === "string" && v.trim());
  const byValue = new Map();
  const byGroup = new Map();

  for (const [key, value] of entries) {
    const bucket = byValue.get(value) || [];
    bucket.push(key);
    byValue.set(value, bucket);

    const seen = new Set();
    for (const g of ngrams(contentWords(value))) {
      if (seen.has(g)) continue;
      seen.add(g);
      const rec = byGroup.get(g) || { group: g, keys: [], values: [] };
      rec.keys.push(key);
      rec.values.push(value);
      byGroup.set(g, rec);
    }
  }

  const identical = [...byValue.entries()]
    .filter(([, keys]) => keys.length >= 2)
    .map(([value, keys]) => ({ value, keys, n: keys.length }))
    .sort((a, b) => b.n - a.n || a.value.localeCompare(b.value, "fr"));

  const groups = [...byGroup.values()]
    .filter((rec) => rec.keys.length >= 2)
    .map((rec) => ({ ...rec, n: rec.keys.length }))
    .sort((a, b) => b.n - a.n || b.group.split(" ").length - a.group.split(" ").length || a.group.localeCompare(b.group, "fr"));

  return { identical, groups };
}

function quote(s) {
  return JSON.stringify(s);
}

function extractConstMaps(source) {
  const maps = {};
  const re = /const\s+([A-Z][A-Z0-9_]*)\s*=\s*\{([\s\S]*?)\};/g;
  for (const m of source.matchAll(re)) {
    const obj = {};
    for (const kv of m[2].matchAll(/(\w+)\s*:\s*["']([^"']+)["']/g)) {
      obj[kv[1]] = kv[2];
    }
    if (Object.keys(obj).length) maps[m[1]] = obj;
  }
  return maps;
}

function findDetailsBlocks(src) {
  const blocks = [];
  const openRe = /<details\b[^>]*>/gi;
  let m;
  while ((m = openRe.exec(src))) {
    const innerStart = m.index + m[0].length;
    let depth = 1;
    let i = innerStart;
    while (depth > 0 && i < src.length) {
      const rest = src.slice(i);
      const nextOpen = rest.search(/<details\b/i);
      const nextClose = rest.search(/<\/details>/i);
      if (nextClose < 0) break;
      if (nextOpen >= 0 && nextOpen < nextClose) {
        depth += 1;
        i += nextOpen + 1;
      } else {
        depth -= 1;
        if (depth === 0) {
          blocks.push(src.slice(innerStart, i + nextClose));
        }
        i += nextClose + 10;
      }
    }
  }
  return blocks;
}

function expandAliases(jsx, fileSrc) {
  let out = jsx;
  for (const m of jsx.matchAll(/\{([A-Za-z_]\w*)\}/g)) {
    const name = m[1];
    if (name === "t" || name === "true" || name === "false") continue;
    const decl = fileSrc.match(new RegExp(`const\\s+${name}\\s*=\\s*([\\s\\S]*?);`));
    if (decl) out += `\n${decl[1]}`;
  }
  return out;
}

function collectTexts(jsx, dict, maps) {
  const texts = [];
  for (const m of jsx.matchAll(/\bt\(\s*["']([^"']+)["']/g)) {
    if (dict[m[1]]) texts.push(String(dict[m[1]]));
  }
  for (const m of jsx.matchAll(/\bt\(\s*([A-Z][A-Z0-9_]*)\s*\[/g)) {
    const map = maps[m[1]];
    if (!map) continue;
    for (const key of Object.values(map)) {
      if (dict[key]) texts.push(String(dict[key]));
    }
  }
  for (const m of jsx.matchAll(/["'`]([^"'`]{3,})["'`]/g)) {
    const raw = m[1].trim();
    if (raw && !raw.includes("${") && !raw.includes("className") && !/^[a-z]+(-[a-z0-9]+)+$/.test(raw)) {
      texts.push(raw);
    }
  }
  if (/\$\{[^}]+\}\s*h\b/.test(jsx) || /budget\.hours/.test(jsx) || /horizonH/.test(jsx)) {
    texts.push("HORIZON_H");
  }
  return [...new Set(texts.map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean))];
}

function splitSummaryBody(detailsInner) {
  const m = detailsInner.match(/<summary\b[^>]*>([\s\S]*?)<\/summary>/i);
  if (!m) return { summary: "", body: detailsInner };
  return {
    summary: m[1],
    body: detailsInner.slice(m.index + m[0].length),
  };
}

/**
 * Compare le texte du <summary> (état replié) au contenu déplié.
 * Un même libellé dans les deux = redite à l'écran quand le panneau est ouvert.
 */
export function analyzeFolded(source, dict) {
  const maps = extractConstMaps(source);
  const hits = [];
  for (const inner of findDetailsBlocks(source)) {
    const { summary, body } = splitSummaryBody(inner);
    if (!summary.trim()) continue;
    const summaryTexts = collectTexts(expandAliases(summary, source), dict, maps);
    const bodyTexts = collectTexts(body, dict, maps);
    const bodySet = new Set(bodyTexts);
    const dups = summaryTexts.filter((s) => bodySet.has(s) && (contentWords(s).length >= 1 || s === "HORIZON_H"));
    if (dups.length) hits.push({ dups, summary: summaryTexts, body: bodyTexts });
  }
  return hits;
}

export function analyzeFoldedFiles(files, dict) {
  const hits = [];
  for (const file of files) {
    const src = readFileSync(file, "utf8");
    for (const hit of analyzeFolded(src, dict)) {
      hits.push({ file, ...hit });
    }
  }
  return hits;
}

function componentFiles() {
  const dir = join(here, "../src/components");
  return readdirSync(dir)
    .filter((name) => name.endsWith(".jsx"))
    .map((name) => join(dir, name));
}

export function formatReport(report) {
  const lines = [];
  lines.push("# Redites i18n (src/i18n/fr.js)");
  lines.push("");
  lines.push("## Valeurs identiques sous deux clés ou plus");
  if (!report.identical.length) {
    lines.push("(aucune)");
  } else {
    for (const row of report.identical) {
      lines.push(`${row.n}\t${quote(row.value)}`);
      lines.push(`\t${row.keys.join(", ")}`);
    }
  }
  lines.push("");
  lines.push("## Groupes de ≥ 2 mots (hors mots vides) dans ≥ 2 valeurs");
  if (!report.groups.length) {
    lines.push("(aucun)");
  } else {
    for (const row of report.groups) {
      lines.push(`${row.n}\t${quote(row.group)}`);
      lines.push(`\t${row.keys.join(", ")}`);
    }
  }
  lines.push("");
  return lines.join("\n");
}

export function formatFoldedReport(hits) {
  const lines = ["# Redites repli / dépli (<summary> vs contenu)", ""];
  if (!hits.length) {
    lines.push("(aucune)");
    lines.push("");
    return lines.join("\n");
  }
  for (const hit of hits) {
    const where = hit.file ? `${hit.file}: ` : "";
    lines.push(`${where}${hit.dups.map((d) => quote(d)).join(", ")}`);
  }
  lines.push("");
  return lines.join("\n");
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const report = analyze(fr);
  process.stdout.write(formatReport(report));
  const folded = analyzeFoldedFiles(componentFiles(), fr);
  process.stdout.write(formatFoldedReport(folded));
}

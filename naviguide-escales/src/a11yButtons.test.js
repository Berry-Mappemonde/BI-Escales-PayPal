import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const srcDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(srcDir, "..");

// Keep exceptions reviewable by exact relative path and opening-tag line.
// Drawing-mode lines are found by their handler, so merges that move App.jsx
// do not break the guard.
function lineOf(relPath, needle) {
  const lines = readFileSync(path.join(repoRoot, relPath), "utf8").split("\n");
  const index = lines.findIndex((line) => line.includes(needle));
  return `${relPath}:${index + 1}`;
}

const ALLOW_LIST = new Set([
  // Drawing-mode controls are an explicit protected area per local NAVIGUIDE rules.
  lineOf("src/App.jsx", "<button type=\"button\" onClick={handleDrawUndo}"),
  lineOf("src/App.jsx", "<button type=\"button\" onClick={handleDrawRedo}"),
  // "Draw your own route" section (delete route button) is protected: not modified.
  "src/components/Sidebar.jsx:226",
]);

function jsxFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    return entry.isDirectory() ? jsxFiles(fullPath) : entry.name.endsWith(".jsx") ? [fullPath] : [];
  });
}

function buttonCandidates(source, importedIcons) {
  const results = [];
  const tagPattern = /<\/?button\b[^>]*>/g;
  let match;
  while ((match = tagPattern.exec(source))) {
    if (match[0].startsWith("</")) continue;
    const opening = match[0];
    let depth = 1;
    let close;
    while ((close = tagPattern.exec(source))) {
      if (close[0].startsWith("</")) depth -= 1;
      else if (!close[0].endsWith("/>")) depth += 1;
      if (depth === 0) break;
    }
    if (!close) break;
    const body = source.slice(match.index + opening.length, close.index);
    const accessibleName = /\baria-(?:label|labelledby)\s*=/.test(opening);
    const imports = [...importedIcons].join("|");
    let remainder = body;
    if (imports) remainder = remainder.replace(new RegExp(`<(?:(?:${imports}))\\b[^>]*\\/>`, "g"), "");
    remainder = remainder.replace(/<svg\b[^>]*>[\s\S]*?<\/svg>/g, "").replace(/<svg\b[^>]*\/>/g, "");
    const hasIcon = /<svg\b|<\w+\b[^>]*\/>|\p{Extended_Pictographic}/u.test(body);
    const iconOnlyExpression = /^\s*\{\s*(?:\w+\s*\?\s*)?<\w+\b[^>]*\/>\s*(?:\:\s*<\w+\b[^>]*\/>)?\s*\}\s*$/.test(body);
    const emojiText = remainder.replace(/\{[^}]*\}/g, "");
    const emojiOnly = /\p{Extended_Pictographic}/u.test(emojiText) && /^[\s\p{Extended_Pictographic}\uFE0F\u200D]+$/u.test(emojiText);
    const onlyIcons = hasIcon && (!remainder.trim() || iconOnlyExpression || emojiOnly);
    if (!accessibleName && onlyIcons) {
      const line = source.slice(0, match.index).split("\n").length;
      results.push({ line, opening });
    }
    tagPattern.lastIndex = close.index + close[0].length;
  }
  return results;
}

test("icon-only buttons have accessible names", () => {
  const offenders = [];
  for (const file of jsxFiles(srcDir)) {
    const source = readFileSync(file, "utf8");
    const importedIcons = new Set();
    for (const match of source.matchAll(/import\s*\{([^}]+)\}\s*from\s*["']lucide-react["']/g)) {
      for (const specifier of match[1].split(",")) {
        const name = specifier.trim().split(/\s+as\s+/).at(-1);
        if (name) importedIcons.add(name);
      }
    }
    const relative = path.relative(repoRoot, file).split(path.sep).join("/");
    for (const { line } of buttonCandidates(source, importedIcons)) {
      if (!ALLOW_LIST.has(`${relative}:${line}`)) offenders.push(`${relative}:${line}`);
    }
  }
  assert.deepEqual(offenders, [], `Icon-only buttons need aria-label/aria-labelledby:\n${offenders.join("\n")}`);
});

import { readFileSync, existsSync } from "node:fs";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const readmes = ["README.md", "README.fr.md"];

function stripFences(md) {
  return md.replace(/```[\s\S]*?```/g, "");
}

function markdownTargets(md) {
  const out = [];
  const re = /\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  let m;
  while ((m = re.exec(md))) out.push(m[1]);
  return out;
}

function codePaths(md) {
  const out = [];
  const re = /`([^`\n]+)`/g;
  let m;
  while ((m = re.exec(md))) out.push(m[1]);
  return out;
}

function isExternal(url) {
  return /^(https?:|mailto:|tel:)/i.test(url);
}

function repoPath(raw) {
  const pathPart = decodeURIComponent(raw.split("#")[0]);
  if (!pathPart) return null;
  const abs = resolve(repoRoot, pathPart);
  if (abs !== repoRoot && !abs.startsWith(repoRoot + "/")) return { raw, reason: "escapes repo" };
  return { raw, abs };
}

describe("README relative links", () => {
  for (const name of readmes) {
    it(`${name} points at files that exist`, () => {
      const md = stripFences(readFileSync(join(repoRoot, name), "utf8"));
      const missing = [];
      for (const raw of markdownTargets(md)) {
        if (isExternal(raw) || raw.startsWith("#")) continue;
        const hit = repoPath(raw);
        if (!hit) continue;
        if (hit.reason || !existsSync(hit.abs)) missing.push(raw);
      }
      for (const raw of codePaths(md)) {
        if (!/^(naviguide-simulator\/|\.github\/|docs\/|infra\/)/.test(raw)) continue;
        if (raw.includes("*")) continue;
        const hit = repoPath(raw);
        if (!hit || hit.reason || !existsSync(hit.abs)) missing.push(raw);
      }
      assert.deepEqual(missing, []);
    });
  }
});

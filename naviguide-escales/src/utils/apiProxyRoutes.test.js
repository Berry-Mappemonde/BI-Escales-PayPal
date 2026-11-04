// Chaque chemin d'API appelé par le front doit être relayé vers le serveur
// par le proxy Vite (dev / preview) et par nginx (prod). Sinon le navigateur
// reçoit index.html à la place du JSON (cas de /zee/at).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const simRoot = path.resolve(here, "../..");
const repoRoot = path.resolve(simRoot, "..");

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(js|jsx)$/.test(name) && !/\.test\.js$/.test(name)) out.push(p);
  }
  return out;
}

// Préfixes servis par le serveur (FastAPI) : premier segment des routes.
function serverPrefixes() {
  const dir = path.join(simRoot, "server");
  const set = new Set();
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".py")) continue;
    const src = readFileSync(path.join(dir, name), "utf8");
    for (const m of src.matchAll(/@\w+\.(?:get|post|put|delete|patch|api_route)\(\s*"\/([A-Za-z0-9_-]+)/g)) {
      set.add(m[1]);
    }
  }
  return set;
}

// Chemins appelés par le front : `${API_URL}/zee/at?...`, fetch("/voyage/..."), etc.
function frontPaths() {
  const found = new Map();
  const bases = "(?:API_URL|API|api|POLAR_API_URL|BI_BASE)";
  const reTpl = new RegExp("\\$\\{" + bases + "\\}(/[A-Za-z0-9_/.-]*)", "g");
  const reLit = /\bfetch\(\s*[`'"](\/[A-Za-z0-9_/.-]*)/g;
  for (const file of walk(path.join(simRoot, "src"))) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(reTpl)) {
      let p = m[1];
      if (m[0].startsWith("${BI_BASE}")) p = "/bi" + p;
      found.set(p, path.relative(simRoot, file));
    }
    for (const m of src.matchAll(reLit)) found.set(m[1], path.relative(simRoot, file));
  }
  return found;
}

function probe(p) {
  // Chemin concret à tester : on complète un chemin terminé par « / ».
  return p.endsWith("/") ? p + "x" : p;
}

function viteProxyKeys() {
  const src = readFileSync(path.join(simRoot, "vite.config.js"), "utf8");
  const block = src.slice(src.indexOf("const proxy = {"));
  const body = block.slice(0, block.indexOf("\n};"));
  return [...body.matchAll(/^\s{6}"(\/[^"]+)":/gm)].map((m) => m[1]);
}

function nginxApiLocations() {
  const src = readFileSync(path.join(repoRoot, "infra/vps/naviguide/nginx-simulator.conf"), "utf8");
  const locs = [];
  for (const m of src.matchAll(/^\s*location\s+(=|~\*?|\^~)?\s*(\S+)\s*\{/gm)) {
    const [, mod, arg] = m;
    if (!mod && arg === "/") continue; // repli SPA → index.html
    if (mod === "=") locs.push((p) => p === arg);
    else if (mod && mod.startsWith("~")) {
      const re = new RegExp(arg, mod === "~*" ? "i" : "");
      locs.push((p) => re.test(p));
    } else locs.push((p) => p.startsWith(arg));
  }
  return locs;
}

const served = serverPrefixes();
const calls = [...frontPaths()].filter(([p]) => served.has(p.split("/")[1]));

test("le front appelle bien des chemins d'API (sanity)", () => {
  const firsts = new Set(calls.map(([p]) => p.split("/")[1]));
  for (const seg of ["ici", "voyage", "route", "zee", "logbook", "escale"]) {
    assert.ok(firsts.has(seg), `préfixe /${seg} non trouvé dans src/`);
  }
});

test("chaque chemin d'API du front est relayé par le proxy Vite", () => {
  const keys = viteProxyKeys();
  const missing = calls
    .filter(([p]) => !keys.some((k) => probe(p).startsWith(k)))
    .map(([p, f]) => `${p} (${f})`);
  assert.deepEqual(missing, [], "absents du proxy de vite.config.js");
});

test("chaque chemin d'API du front est relayé par nginx (pas index.html)", () => {
  const locs = nginxApiLocations();
  const missing = calls
    .filter(([p]) => !locs.some((match) => match(probe(p))))
    .map(([p, f]) => `${p} (${f})`);
  assert.deepEqual(missing, [], "absents de nginx-simulator.conf");
});

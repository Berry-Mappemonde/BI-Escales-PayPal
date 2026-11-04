import assert from "node:assert/strict";
import test from "node:test";
import { fetchWatchSettings, parseWatchSettings, saveWatchSettings } from "./watchSettings.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const res = (status, body) => ({ ok: status < 400, status, json: async () => body });

test("R42 : parseWatchSettings n'accepte qu'un booléen servi", () => {
  assert.deepEqual(parseWatchSettings({ enabled: true, source: "setting" }), { enabled: true, source: "setting" });
  assert.equal(parseWatchSettings({ enabled: "1" }), null);
  assert.equal(parseWatchSettings(null), null);
});

test("R42 : lecture et écriture passent par /escale/watch/settings avec la clé admin", async () => {
  const calls = [];
  const f = async (url, init) => { calls.push([url, init]); return res(200, { enabled: !init ? true : false, source: "setting" }); };
  assert.deepEqual(await fetchWatchSettings(f, "http://api"), { enabled: true, source: "setting" });
  const out = await saveWatchSettings(false, f, "http://api", { "X-Naviguide-Admin": "k" });
  assert.equal(out.ok, true);
  assert.equal(calls[1][0], "http://api/escale/watch/settings");
  assert.equal(calls[1][1].method, "POST");
  assert.equal(calls[1][1].headers["X-Naviguide-Admin"], "k");
  assert.deepEqual(JSON.parse(calls[1][1].body), { enabled: false });
});

test("R42 : refus admin et panne réseau distingués", async () => {
  assert.deepEqual(await saveWatchSettings(true, async () => res(401, {}), ""), { ok: false, reason: "admin" });
  assert.deepEqual(await saveWatchSettings(true, async () => res(503, {}), ""), { ok: false, reason: "error" });
  assert.deepEqual(await saveWatchSettings(true, async () => { throw new Error("x"); }, ""), { ok: false, reason: "error" });
});

test("R42 : libellés FR et EN présents et distincts", () => {
  for (const k of ["tavilyWatchLabel", "tavilyWatchHint", "tavilyWatchAdmin", "tavilyWatchError"]) {
    assert.ok(fr[k] && en[k], k);
    assert.notEqual(fr[k], en[k], k);
  }
});

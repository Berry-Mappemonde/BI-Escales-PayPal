import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "EscaleSheet.jsx"), "utf8");
const hook = readFileSync(join(here, "..", "hooks", "useEscaleSheet.js"), "utf8");

describe("EscaleSheet contract", () => {
  it("every place links to the map, its site and Google Maps; empty sections are not rendered", () => {
    assert.match(src, /googleMapsUrl\(item\.lat, item\.lon\)/);
    assert.match(src, /onFocus\(\{ name: item\.name, lat: item\.lat, lon: item\.lon, kind: SUB_KIND\[sub\]/);
    assert.match(src, /target="_blank" rel="noopener noreferrer"/);
    assert.match(src, /Object\.keys\(sections\)/, "sections come from the server: nothing invented client-side");
    assert.match(src, /escale-enrich/, "phrase sourcée de la perle, pas un fetch client");
    assert.doesNotMatch(src, /fetch\(|Nemotron|Tavily|Nebius/i);
  });

  it("the paragraph is shown only when the cascade produced one; no listen button", () => {
    assert.match(src, /fiche\?\.paragraph\?\.status === "ready" \? fiche\.paragraph\.text : ""/);
    assert.doesNotMatch(src, /ListenButton/);
    assert.doesNotMatch(src, /escale-listen/);
    assert.match(src, /data-testid="escale-close"/);
  });

  it("the hook asks GET /escale once per (stop, lang) and keeps it in this tab", () => {
    assert.match(hook, /\/escale\?name=\$\{encodeURIComponent\(stop\.name\)\}&lat=\$\{stop\.lat\}&lon=\$\{stop\.lon\}&lang=/);
    assert.match(hook, /cacheRef\.current\.set\(key, fiche\)/);
    assert.match(hook, /controller\.abort\(\)/);
    assert.equal((hook.match(/useEffect\(/g) || []).length, 1, "one fetch on stop/lang, not per render");
  });

  it("affiche le nom lisible ; la clé du hook reste le nom stocké", () => {
    assert.match(src, /import \{ displayStopName \} from "\.\.\/utils\/stopLabels\.js"/);
    assert.match(src, /\{displayStopName\(stop\.name, lang, t\)\}/);
    assert.doesNotMatch(src, />\{stop\.name\}</);
    assert.match(hook, /\$\{stop\.name\}\|\$\{stop\.lat\.toFixed\(2\)\}/);
    assert.doesNotMatch(hook, /displayStopName/);
  });

  it("shows the paragraph source under the text and does not fetch /escale itself", () => {
    assert.match(src, /testId="escale-source"/);
    assert.match(src, /LlmSourceBadge/);
    assert.doesNotMatch(src, /useEffect/);
    assert.doesNotMatch(src, /\/escale/);
  });
});

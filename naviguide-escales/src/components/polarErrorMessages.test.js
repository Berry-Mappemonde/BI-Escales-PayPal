import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "ToolsSidebar.jsx"), "utf8");
const errorMapper = source.slice(source.indexOf("export function polarErrorDetail"), source.indexOf("function PolarVmgRow"));
const layerToggles = readFileSync(join(here, "LayerToggles.jsx"), "utf8");

describe("erreurs du service des polaires", () => {
  it("ne transmet jamais les détails serveur ni le statut HTTP", () => {
    assert.match(errorMapper, /return t\("polarNetworkError"\)/);
    assert.doesNotMatch(errorMapper, /return error\.detail|HTTP \$\{error\.status\}/);
    assert.equal(fr.polarServiceUnavailable, "Le service des polaires est momentanément indisponible. Réessayez dans quelques instants.");
    assert.equal(en.polarServiceUnavailable, "The polar service is temporarily unavailable. Please try again shortly.");
    assert.doesNotMatch(fr.polarServiceUnavailable + en.polarServiceUnavailable, /HTTP|\{status\}/);
  });

  it("n'expose pas les codes d'erreur des couches dans les titres UI", () => {
    assert.match(layerToggles, /error \? `\$\{t\(titleKey\)\} : \$\{t\("layerUnavailable"\)\}`/);
    assert.doesNotMatch(layerToggles, /titleBase = error \? `\$\{t\(titleKey\)\} : \$\{error\}`/);
    assert.equal(fr.layerUnavailable, "données indisponibles");
    assert.equal(en.layerUnavailable, "data unavailable");
  });
});

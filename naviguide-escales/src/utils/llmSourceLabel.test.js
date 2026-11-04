import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import { isAiGeneratedSource, llmSourceI18nKey, llmSourceLabel, llmSourceShowsBrands } from "./llmSourceLabel.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "llmSourceLabel.js"), "utf8");
const badge = readFileSync(join(here, "../components/LlmSourceBadge.jsx"), "utf8");

const tEn = (key) => en[key];

describe("AI transparency — source helpers", () => {
  it("exports isAiGeneratedSource and maps legacy film ids", () => {
    assert.match(src, /export function isAiGeneratedSource/);
    assert.match(src, /export function isLlmWrittenSource/);
    assert.match(src, /storySourceSuperReviewed/);
    assert.match(src, /reviewedBy/);
    assert.match(src, /nemotron-super-token-factory/);
    assert.match(src, /s === "rules" \|\| s === "budget"/);
    assert.match(src, /\+local/);
    const keyFn = src.slice(src.indexOf("export function llmSourceI18nKey"));
    const reviewed = keyFn.indexOf("storySourceSuperReviewed");
    const ultra = keyFn.indexOf('endsWith("-ultra")');
    assert.ok(reviewed > 0 && reviewed < ultra, "reviewed-ultra avant le suffixe ultra");
  });
});

describe("llmSourceI18nKey", () => {
  it("maps Nemotron suffixes and does not disguise NIM as rules", () => {
    assert.match(src, /endsWith\("-ultra"\)/);
    assert.match(src, /"-nano"/);
    assert.match(src, /gpt-oss\|nvidia-gpt\|\\bnim\\b/);
    assert.match(src, /return "storySourceNim"/);
    const nimIdx = src.indexOf("storySourceNim");
    const rulesReturn = src.lastIndexOf('return "storySourceRules"');
    assert.ok(nimIdx > 0 && nimIdx < rulesReturn, "NIM avant le repli rules");
    assert.match(src, /lower === "nemotron" \|\| lower\.includes\("super"\)/);
  });

  it("Lightning relu par Ultra ne devient pas Super relu par Ultra", () => {
    const lightning = llmSourceI18nKey("nemotron-lightning", "nemotron-ultra");
    assert.equal(lightning, "storySourceLightning");
    assert.equal(llmSourceI18nKey("nemotron-lightning", null), "storySourceLightning");
    assert.doesNotMatch(en[lightning], /reviewed by Ultra/i);
    assert.doesNotMatch(fr[lightning], /relu par Ultra/i);
    assert.equal(llmSourceI18nKey("nemotron-super", "nemotron-ultra"), "storySourceSuperReviewed");
    assert.equal(llmSourceI18nKey("nemotron", "nemotron-ultra"), "storySourceSuperReviewed");
    assert.match(en.storySourceSuperReviewed, /Nemotron 3\.5 Super VL/);
    assert.doesNotMatch(en.storySourceSuperReviewed, /Nemotron 3 Super\b/);
    assert.match(fr.storySourceSuperReviewed, /Nemotron 3\.5 Super VL/);
    assert.match(en.storySourceSuperReviewed, /Token Factory/);
    assert.match(en.storySourceSuperReviewed, /reviewed by Ultra/);
    assert.match(fr.storySourceSuperReviewed, /Token Factory/);
    assert.match(fr.storySourceSuperReviewed, /relu par Ultra/);
    assert.match(llmSourceLabel("nemotron-super", tEn, "nemotron-ultra"), /Token Factory/);
    assert.equal(llmSourceShowsBrands("nemotron-super-reviewed-ultra"), true);
    assert.doesNotMatch(llmSourceLabel("openrouter", tEn, "nemotron-ultra"), /Token Factory/);
    assert.doesNotMatch(llmSourceLabel("nvidia-gpt-oss-20b", tEn, "nemotron-ultra"), /Token Factory/);
  });

  it("names each Token Factory tier exactly, and never a fallback", () => {
    const exact = {
      "nemotron-nano": "Nemotron 3 Nano 30B · Token Factory",
      "route-nano": "Nemotron 3 Nano 30B · Token Factory",
      "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": "Nemotron 3 Nano 30B · Token Factory",
      "nemotron-lightning": "Nemotron 3.5 Lightning · Token Factory",
      "nvidia/Nemotron-3_5-Lightning": "Nemotron 3.5 Lightning · Token Factory",
      "nemotron-super": "Nemotron 3.5 Super VL · Token Factory",
      "nemotron-super-vl": "Nemotron 3.5 Super VL · Token Factory",
      "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super 120B · Token Factory",
      "nvidia/Nemotron-3.5-Super-VL": "Nemotron 3.5 Super VL · Token Factory",
      "nemotron-ultra": "Nemotron 3 Ultra · Token Factory",
      "nvidia/Nemotron-3-Ultra-550b-a55b": "Nemotron 3 Ultra · Token Factory",
      openrouter: "OpenRouter",
      "openai/gpt-4o-mini": "OpenRouter",
      claude: "Claude",
      "claude-haiku-4-5": "Claude",
      "nvidia-gpt-oss-20b": "NVIDIA NIM (fallback)",
      "openai/gpt-oss-20b": "NVIDIA NIM (fallback)",
      nim: "NVIDIA NIM (fallback)",
    };
    for (const [source, label] of Object.entries(exact)) {
      assert.equal(llmSourceLabel(source, tEn), label, source);
      assert.equal(en[llmSourceI18nKey(source)], label, source);
    }
    assert.equal(fr.storySourceOpenrouter, "OpenRouter");
    assert.equal(fr.storySourceClaude, "Claude");
    assert.equal(fr.llmBrandNvidia, "NVIDIA");
    assert.equal(fr.llmBrandNebius, "Nebius");
    assert.equal(en.llmBrandNvidia, "NVIDIA");
    assert.equal(en.llmBrandNebius, "Nebius");
    for (const source of ["openrouter", "openai/gpt-4o-mini", "claude", "claude-haiku-4-5", "nvidia-gpt-oss-20b", "openai/gpt-oss-20b", "nim"]) {
      assert.equal(llmSourceShowsBrands(source), false, source);
      assert.doesNotMatch(llmSourceLabel(source, tEn), /Token Factory/, source);
      assert.doesNotMatch(llmSourceLabel(source, (key) => fr[key]), /Token Factory/, source);
    }
    for (const source of [
      "nemotron-nano",
      "route-nano",
      "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
      "nemotron-lightning",
      "nvidia/Nemotron-3_5-Lightning",
      "nemotron-super-vl",
      "nvidia/Nemotron-3.5-Super-VL",
      "nemotron-ultra",
      "nvidia/Nemotron-3-Ultra-550b-a55b",
    ]) {
      assert.equal(llmSourceShowsBrands(source), true, source);
      assert.match(llmSourceLabel(source, tEn), /Nemotron .+ · Token Factory/, source);
    }
  });
});

describe("LlmSourceBadge — texte seul", () => {
  it("n'a aucune image de logo et nomme NVIDIA et Nebius en texte", () => {
    assert.doesNotMatch(badge, /<img\b/);
    assert.doesNotMatch(badge, /<svg\b/i);
    assert.doesNotMatch(badge, /backgroundImage|background-image/);
    assert.doesNotMatch(badge, /background\s*:\s*["'`]?\s*url\s*\(/i);
    assert.doesNotMatch(badge, /bg-\[url\(/);
    assert.doesNotMatch(badge, /\.svg|LLM_BRAND_LOGOS/);
    assert.doesNotMatch(src, /<img\b|<svg\b|backgroundImage|background\s*:\s*["'`]?\s*url\s*\(|bg-\[url\(|\.svg|LLM_BRAND_LOGOS/i);
    const brandDir = join(here, "../assets/brand");
    const images = readdirSync(brandDir).filter((name) => /\.(svg|png|webp|gif|jpe?g)$/i.test(name));
    assert.deepEqual(images, []);
    assert.equal(isAiGeneratedSource("openai/gpt-4o-mini"), true);
    assert.match(badge, /llmBrandNvidia/);
    assert.match(badge, /llmBrandNebius/);
    assert.match(badge, /llmSourceShowsBrands/);
    assert.match(badge, /llmSourceLabel/);
  });
});

describe("libellés alignés sur les modèles servis (llm_budget.DEFAULT_MODELS)", () => {
  const tEnL = (key) => en[key] ?? key;
  it("palier write : Super VL par défaut, Super 120B seulement si le modèle servi le nomme", () => {
    assert.equal(llmSourceLabel("nemotron-super", tEnL), "Nemotron 3.5 Super VL · Token Factory");
    assert.equal(llmSourceLabel("nemotron-super", tEnL, null, "nvidia/Nemotron-3.5-Super-VL"), "Nemotron 3.5 Super VL · Token Factory");
    assert.equal(llmSourceLabel("nemotron-super", tEnL, null, "nvidia/nemotron-3-super-120b-a12b"), "Nemotron 3 Super 120B · Token Factory");
    assert.equal(llmSourceI18nKey("nemotron-super", "nemotron-ultra", "nvidia/nemotron-3-super-120b-a12b"), "storySourceSuper120bReviewed");
    assert.equal(llmSourceI18nKey("nemotron-super", "nemotron-ultra", "nvidia/Nemotron-3.5-Super-VL"), "storySourceSuperReviewed");
    assert.equal(llmSourceI18nKey("nemotron", null, "nvidia/Nemotron-3_5-Lightning"), "storySourceLightning");
    assert.equal(llmSourceShowsBrands("nvidia/nemotron-3-super-120b-a12b"), true);
  });
  it("aucun libellé i18n ne nomme encore « Nemotron 3 Super » sans 120B", () => {
    for (const dict of [en, fr]) {
      for (const [key, value] of Object.entries(dict)) {
        if (typeof value !== "string") continue;
        assert.doesNotMatch(value, /Nemotron 3 Super(?! 120B)/, key);
        assert.doesNotMatch(value, /Nemotron 3 Nano(?! 30B)/, key);
      }
    }
  });
});

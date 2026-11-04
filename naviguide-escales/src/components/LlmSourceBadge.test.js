import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { transformWithOxc } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");

describe("LlmSourceBadge texte seul", () => {
  it("ne rend ni img, ni backgroundImage, ni url()", async () => {
    const dir = mkdtempSync(join(root, ".badge-render-"));
    try {
      mkdirSync(join(dir, "i18n"));
      mkdirSync(join(dir, "utils"));
      mkdirSync(join(dir, "components"));
      const labelSrc = readFileSync(join(root, "src/utils/llmSourceLabel.js"), "utf8");
      assert.doesNotMatch(labelSrc, /import .+\.svg|LLM_BRAND_LOGOS|<img\b|<svg\b/i);
      writeFileSync(join(dir, "utils/llmSourceLabel.js"), labelSrc);
      writeFileSync(join(dir, "i18n/LangContext.js"), `
import { createContext, useContext } from "react";
export const LangContext = createContext(null);
export function useLang() {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used inside LangProvider");
  return ctx;
}
`);
      const jsx = readFileSync(join(root, "src/components/LlmSourceBadge.jsx"), "utf8");
      const transformed = await transformWithOxc(jsx, "LlmSourceBadge.jsx");
      const code = transformed.code.replaceAll("../i18n/LangContext.jsx", "../i18n/LangContext.js");
      writeFileSync(join(dir, "components/LlmSourceBadge.js"), code);
      const { LangContext } = await import(pathToFileURL(join(dir, "i18n/LangContext.js")).href);
      const { LlmSourceBadge } = await import(pathToFileURL(join(dir, "components/LlmSourceBadge.js")).href);
      const en = (await import(pathToFileURL(join(root, "src/i18n/en.js")).href)).default;
      const t = (key, vars = {}) => Object.entries(vars).reduce(
        (s, [k, v]) => s.replace(`{${k}}`, String(v)),
        en[key] ?? key,
      );
      const render = (source) => renderToStaticMarkup(createElement(
        LangContext.Provider,
        { value: { lang: "en", t } },
        createElement(LlmSourceBadge, { source, textOnly: true, testId: "film-source" }),
      ));
      const html = render("nemotron-super");
      assert.match(html, /Models · AI-generated content \(model: Nemotron 3\.5 Super VL · Token Factory\)/);
      const nano = render("nemotron-nano");
      assert.match(nano, /Models · AI-generated content \(model: Nemotron 3 Nano 30B · Token Factory\)/);
      assert.doesNotMatch(nano, /<img\b|<svg\b|\.svg|background-image|backgroundImage|url\(/i);
      assert.match(html, /<span>NVIDIA<\/span><span aria-hidden="true">·<\/span><span>Nebius<\/span>/);
      assert.doesNotMatch(html, /<img\b/i);
      assert.doesNotMatch(html, /<svg\b/i);
      assert.doesNotMatch(html, /\.svg/i);
      assert.doesNotMatch(html, /background-image|backgroundImage/i);
      assert.doesNotMatch(html, /url\(/i);
      for (const [source, exact, banned] of [
        ["openrouter", "AI-generated content (model: OpenRouter)", /Token Factory|NVIDIA|Nebius/],
        ["claude", "AI-generated content (model: Claude)", /Token Factory|NVIDIA|Nebius/],
        ["nvidia-gpt-oss-20b", "AI-generated content (model: NVIDIA NIM (fallback))", /Token Factory|Nebius/],
      ]) {
        const fallback = render(source);
        assert.match(fallback, new RegExp(exact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
        assert.doesNotMatch(fallback, banned);
        assert.doesNotMatch(fallback, /<img\b|<svg\b|\.svg|background-image|backgroundImage|url\(/i);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

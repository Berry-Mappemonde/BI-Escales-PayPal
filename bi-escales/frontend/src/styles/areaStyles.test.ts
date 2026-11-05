import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Read from disk: Vitest stubs CSS imports to an empty string, even with ?raw.
const read = (file: string) =>
  readFileSync(resolve(process.cwd(), "src/components", file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe.each(["stop/stop-panel.css", "captain/captain-card.css", "treasurer-panel.css"])("%s", (file) => {
  const css = read(file);

  it("is not empty", () => {
    expect(css.length).toBeGreaterThan(500);
  });

  it("has no hard-coded colours", () => {
    expect(css.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
    expect(css.match(/\b(rgba?|hsla?)\(/g)).toBeNull();
    expect(css.match(/(?<![-\w])(black|white)(?![-\w])/g)).toBeNull();
  });

  it("does not redefine a global token", () => {
    expect(css.match(/^\s*--(color|text|radius|space|font|shadow|duration)-[\w-]+:/gm)).toBeNull();
  });

  it("does not reach into the PayPal hosts", () => {
    expect(css).not.toMatch(/paypal-(smart|buttons|card|wallet|google|apple)|card-field|pledge-button/i);
  });
});

describe("treasurer-panel.css", () => {
  const css = read("treasurer-panel.css");

  it("stays inside the panel body, leaving the shell's container alone", () => {
    const selectors = css
      .replace(/@media[^{]+\{/g, "")
      .match(/[^{}]+(?=\{)/g)
      ?.flatMap((group) => group.split(","))
      .map((selector) => selector.trim())
      .filter(Boolean);
    expect(selectors?.length).toBeGreaterThan(10);
    for (const selector of selectors ?? []) {
      expect(selector.startsWith(".treasurer-panel .treasurer-panel-body")).toBe(true);
    }
  });

  it("leaves the Captain card's paragraphs to the card", () => {
    expect(css).toContain(".treasurer-panel-body p:not(.captain-card p)");
    expect(css).not.toMatch(/\.treasurer-panel-body p\s*[,{]/);
  });

  it("leaves the Captain card's buttons to the card", () => {
    for (const rule of css.match(/[^{}]*\bbutton\b[^{}]*(?=\{)/g) ?? []) {
      for (const selector of rule.split(",")) {
        expect(selector).toContain(":not(.captain-card button)");
      }
    }
  });
});

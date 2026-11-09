import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const indexHtml = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "..", "index.html"),
  "utf8",
);

describe("index.html site meta", () => {
  it("includes description, Open Graph, Twitter, canonical and favicon", () => {
    expect(indexHtml).toMatch(/<meta\s+name="description"/i);
    expect(indexHtml).toMatch(/property="og:title"/i);
    expect(indexHtml).toMatch(/name="twitter:card"/i);
    expect(indexHtml).toMatch(/rel="canonical"\s+href="https:\/\/escales\.naviguide\.fr\/"/i);
    expect(indexHtml).toMatch(/rel="icon"[^>]+href="\/favicon\.svg"/i);
    expect(indexHtml).not.toMatch(/reçu fiscal|déductib|tax receipt|tax.deduct/i);
  });
});

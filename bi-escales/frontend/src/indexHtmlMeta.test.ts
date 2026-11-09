import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const indexHtml = readFileSync(resolve(frontendRoot, "index.html"), "utf8");

function pngDimensions(filePath: string): { width: number; height: number } {
  const buf = readFileSync(filePath);
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

describe("index.html site meta", () => {
  it("includes description, Open Graph, Twitter, canonical and favicon", () => {
    expect(indexHtml).toMatch(/<meta\s+name="description"/i);
    expect(indexHtml).toMatch(/property="og:title"/i);
    expect(indexHtml).toMatch(/name="twitter:card"/i);
    expect(indexHtml).toMatch(/rel="canonical"\s+href="https:\/\/escales\.naviguide\.fr\/"/i);
    expect(indexHtml).toMatch(/rel="icon"[^>]+href="\/favicon\.svg"/i);
    expect(indexHtml).not.toMatch(/reçu fiscal|déductib|tax receipt|tax.deduct/i);
    expect(indexHtml).toMatch(/lang="en"/i);
    expect(indexHtml).toMatch(/rel="alternate"\s+hreflang="en"/i);
    expect(indexHtml).toMatch(/rel="alternate"\s+hreflang="fr"/i);
    expect(indexHtml).toMatch(/rel="alternate"\s+hreflang="x-default"/i);
    expect(indexHtml).toMatch(/property="og:locale"\s+content="en_US"/i);
    expect(indexHtml).toMatch(/property="og:locale:alternate"\s+content="fr_FR"/i);
    expect(indexHtml).toMatch(/Pay only when we arrive/i);
    expect(indexHtml).not.toMatch(/Pay Only If We Sail|si nous partons/i);
  });

  it("exposes social preview image tags with absolute URLs", () => {
    const ogImage = "https://escales.naviguide.fr/og-image.png";
    expect(indexHtml).toMatch(new RegExp(`property="og:image"\\s+content="${ogImage}"`));
    expect(indexHtml).toMatch(new RegExp(`name="twitter:image"\\s+content="${ogImage}"`));
    expect(indexHtml).toMatch(/name="twitter:card"\s+content="summary_large_image"/i);
  });

  it("describes capture timing instead of pay-only-after-validation copy", () => {
    expect(indexHtml).not.toMatch(/only pay after|après validation de l'escale|arrivée validée/i);
    expect(indexHtml).toMatch(/common fund and project gifts at once/i);
  });

  it("ships a 1200×630 og-image.png", () => {
    const dims = pngDimensions(resolve(frontendRoot, "public", "og-image.png"));
    expect(dims).toEqual({ width: 1200, height: 630 });
  });
});

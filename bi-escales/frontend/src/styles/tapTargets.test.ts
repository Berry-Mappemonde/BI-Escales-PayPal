import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Read from disk: Vitest stubs CSS imports to an empty string, even with ?raw.
const read = (file: string) =>
  readFileSync(resolve(process.cwd(), "src", file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Every `@media (pointer: coarse) { … }` block of a stylesheet, joined. */
function coarseRules(css: string): string {
  const blocks: string[] = [];
  const opener = /@media\s*\(pointer:\s*coarse\)\s*\{/g;
  while (opener.exec(css) !== null) {
    let depth = 1;
    let index = opener.lastIndex;
    while (depth > 0 && index < css.length) {
      if (css[index] === "{") depth += 1;
      if (css[index] === "}") depth -= 1;
      index += 1;
    }
    blocks.push(css.slice(opener.lastIndex, index - 1));
  }
  return blocks.join("\n");
}

/** The declarations of the first rule whose selector contains `selector`. */
function rule(css: string, selector: string): string {
  const at = css.indexOf(selector);
  if (at < 0) return "";
  const open = css.indexOf("{", at);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("tap targets on a touch screen", () => {
  const map = coarseRules(read("styles/map-overlays.css"));
  const shell = coarseRules(read("styles/naviguide-shell.css"));
  const captain = coarseRules(read("components/captain/captain-card.css"));

  it("gives a stop's flag a 44px area without resizing the flag", () => {
    const area = rule(map, ".flag-divicon::after");
    expect(area).toMatch(/width:\s*44px/);
    expect(area).toMatch(/height:\s*44px/);
    expect(area).toMatch(/position:\s*absolute/);
    expect(area).not.toMatch(/background|border/);
  });

  it("makes the map's layer toggles 44px tall", () => {
    expect(rule(map, ".ng-layer-toggle")).toMatch(/min-height:\s*44px/);
  });

  it("makes the treasurer page's way back 44px tall", () => {
    expect(rule(shell, ".treasurer-page-back")).toMatch(/min-height:\s*44px/);
  });

  it("widens a citation chip's area and leaves the chip its size", () => {
    expect(rule(captain, "button.captain-cite::after")).toMatch(/inset:\s*-14px -6px/);
    expect(rule(captain, "button:not(.captain-cite)")).toMatch(/min-height:\s*44px/);
  });

  it("changes nothing for a mouse: the rules live in pointer: coarse only", () => {
    const fine = read("styles/map-overlays.css").replace(/@media\s*\(pointer:\s*coarse\)\s*\{[\s\S]*?\n\}/g, "");
    expect(fine).not.toContain(".flag-divicon::after");
    expect(rule(fine, ".ng-layer-control .ng-layer-toggle {")).not.toMatch(/min-height:\s*44px/);
  });
});

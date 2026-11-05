import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Read from disk: Vitest stubs CSS imports to an empty string, even with ?raw.
const read = (file: string) => readFileSync(resolve(process.cwd(), "src/styles", file), "utf8");
const appCss = read("app.css");
const tokensCss = read("tokens.css");

function block(selector: string): Record<string, string> {
  const start = tokensCss.indexOf(selector);
  expect(start).toBeGreaterThan(-1);
  const body = tokensCss.slice(tokensCss.indexOf("{", start) + 1, tokensCss.indexOf("\n}", start));
  const entries = [...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]);
  return Object.fromEntries(entries);
}

const dark = block(':root[data-theme="dark"] {');
const light = block(':root[data-theme="light"] {');

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => Number.parseInt(hex.slice(at, at + 2), 16) / 255);
  const [r, g, b] = channels.map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

describe.each([
  ["dark", dark],
  ["light", light],
])("%s tokens", (_name, set) => {
  it.each(["--color-fg", "--color-fg-2", "--color-fg-3", "--color-accent-fg", "--color-danger", "--color-warning", "--color-success-fg", "--color-marina-verified-fg"])(
    "%s reads on panels and the canvas",
    (token) => {
      expect(contrast(set[token], set["--color-panel"])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(set[token], set["--color-canvas"])).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("keeps text readable on the accent", () => {
    expect(contrast(set["--color-on-accent"], set["--color-accent"])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(["--color-st-triage", "--color-st-todo", "--color-st-progress", "--color-st-review", "--color-st-done", "--color-st-declined", "--color-st-route"])(
    "%s is visible as a mark on a panel",
    (token) => {
      expect(contrast(set[token], set["--color-panel"])).toBeGreaterThanOrEqual(3);
    },
  );

  it("gives each meaning its own colour", () => {
    const meanings = [
      "--color-st-progress",
      "--color-st-done",
      "--color-st-declined",
      "--color-st-review",
      "--color-st-route",
      "--color-st-triage",
      "--color-danger",
      "--color-warning",
    ];
    expect(new Set(meanings.map((token) => set[token])).size).toBe(meanings.length);
  });
});

describe("token sets", () => {
  it("define the same names in both themes", () => {
    expect(Object.keys(light)).toEqual(Object.keys(dark));
  });

  it("keep the Meridian dark values", () => {
    expect(dark).toMatchObject({
      "--color-canvas": "#121212",
      "--color-panel": "#191919",
      "--color-fg": "#ededed",
      "--color-accent": "#4f8cff",
      "--color-danger": "#eb5a5a",
      "--color-st-progress": "#e2b53e",
      "--color-st-done": "#4fb67f",
      "--color-st-review": "#9b87f5",
      "--color-st-declined": "#6f6f6f",
    });
  });

  it("keep the route teal", () => {
    expect(dark["--color-st-route"]).toBe("#3fb3c4");
  });

  it("map each status to the agreed meaning", () => {
    expect(tokensCss).toContain("--color-status-held: var(--color-st-progress);");
    expect(tokensCss).toContain("--color-status-captured: var(--color-st-done);");
    expect(tokensCss).toContain("--color-status-released: var(--color-st-declined);");
    expect(tokensCss).toContain("--color-status-refunded: var(--color-st-review);");
    expect(tokensCss).toContain("--color-status-route: var(--color-st-route);");
    expect(tokensCss).toContain("--color-status-error: var(--color-danger);");
  });
});

describe("naviguide-shell.css", () => {
  const shellCss = read("naviguide-shell.css").replace(/\/\*[\s\S]*?\*\//g, "");

  it("has no hard-coded colours left", () => {
    expect(shellCss.length).toBeGreaterThan(1000);
    expect(shellCss.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
    expect(shellCss.match(/\b(rgba?|hsla?)\(/g)).toBeNull();
    expect(shellCss.match(/(?<![-\w])(black|white)(?![-\w])/g)).toBeNull();
  });

  it("gives every shell colour a value in both themes", () => {
    const names = (selector: string) => {
      const start = shellCss.indexOf(selector);
      const body = shellCss.slice(start, shellCss.indexOf("\n}", start));
      return [...body.matchAll(/(--shell-[\w-]+):/g)].map((match) => match[1]);
    };
    const darkNames = names(':root[data-theme="dark"] {');
    expect(darkNames).toHaveLength(11);
    expect(names(':root[data-theme="light"] {')).toEqual(darkNames);
  });
});

describe("app.css", () => {
  it("has no hard-coded colours left", () => {
    const withoutComments = appCss.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(withoutComments.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
    expect(withoutComments.match(/\b(rgba?|hsla?)\(/g)).toBeNull();
    expect(withoutComments.match(/:\s*(black|white)\b/g)).toBeNull();
  });

  it("loads the tokens first", () => {
    expect(appCss.trimStart().startsWith('@import "./tokens.css";')).toBe(true);
  });
});

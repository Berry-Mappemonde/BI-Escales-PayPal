import type { Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const shotsRoot = path.join(root, "screenshots");
const diagnosticsDir = path.join(root, "diagnostics");
const diagnosticsJson = path.join(diagnosticsDir, "browser-diagnostics.json");

export const ADMIN_KEY = "demo-admin-key";

export type BrowserEvent = {
  kind: "console" | "pageerror" | "requestfailed" | "http";
  level: string;
  message: string;
  sourceFile: string;
  url: string;
  suggestedFix: string;
};

export type StepRecord = {
  step: string;
  screenshot: string;
  events: BrowserEvent[];
};

export type A11yIssue = {
  message: string;
  sourceFile: string;
  suggestedFix: string;
};

type DiagnosticsFile = {
  viewport: string;
  journeys: Array<{
    journey: string;
    steps: StepRecord[];
    a11y: A11yIssue[];
  }>;
};

export function suggestFix(message: string, source: string): string {
  const blob = `${message} ${source}`.toLowerCase();
  if (blob.includes("favicon")) {
    return "Add a real favicon link so the document load does not 404.";
  }
  if (blob.includes("paypal.com/sdk") || blob.includes("sdk/js")) {
    return "Demo mode must render the in-app approve button (VITE_PAYPAL_MOCK=1) and must not inject the PayPal JS SDK without a sandbox client id.";
  }
  if (blob.includes("cors")) {
    return "Keep the Vite /api proxy for local demo, or set ESCALES_CORS_ORIGINS to the exact front origin. Do not use *.";
  }
  if (blob.includes("401") || blob.includes("403") || blob.includes("admin key")) {
    return "Show the treasurer error inline (already on the queue). Do not retry a rejected key in a loop. A deliberate bad-key step will still record this 401.";
  }
  if (blob.includes("409") || blob.includes("illegal")) {
    return "Hide Capture and Void unless the pledge is authorized or vaulted. Pending, failed, and settled rows cannot take those transitions.";
  }
  if (blob.includes("422") || blob.includes("29-day") || blob.includes("arrival")) {
    return "Seed a valid milestone arrival. Horizons of 29 days or more need ESCALES_VAULT_ENABLED; a missing date must stay a visible 422, not a silent AUTHORIZE.";
  }
  if (blob.includes("404")) {
    return "Confirm ESCALES_ENABLED and, for webhooks, ESCALES_WEBHOOKS_ENABLED. Point the front at the same /api path the proxy serves.";
  }
  if (blob.includes("failed to fetch") || blob.includes("networkerror") || blob.includes("err_connection")) {
    return "Start the API on 127.0.0.1:8000 before Vite. The proxy target is VITE_API_PROXY_TARGET.";
  }
  if (blob.includes("resizeobserver")) {
    return "Ignore a benign ResizeObserver loop warning, or stop the layout write that triggers it in the same frame.";
  }
  if (blob.includes("[vite]") || source.includes("/@vite/") || source.includes("node_modules/vite")) {
    return "Dev-server noise. The jury build should be vite preview or a static host, not the HMR client.";
  }
  if (blob.includes("react") && blob.includes("key")) {
    return "Give each list row a stable key (pledge id or milestone id).";
  }
  if (blob.includes("each child in a list")) {
    return "Add a unique key on the mapped React child.";
  }
  return "Open the cited source, reproduce this step, and fix the throw or the failing request before the jury demo.";
}

function sourceLabel(url: string | undefined, line: number | undefined, column: number | undefined): string {
  if (!url) return "(no source)";
  const clean = url.split("?")[0];
  if (line == null || line < 0) return clean;
  const humanLine = line + 1;
  if (column == null || column < 0) return `${clean}:${humanLine}`;
  return `${clean}:${humanLine}:${column + 1}`;
}

export function attachBrowserWatch(page: Page) {
  let step = "00-before-first-step";
  const events: BrowserEvent[] = [];

  const push = (event: BrowserEvent) => {
    events.push(event);
  };

  page.on("console", (msg) => {
    const type = msg.type();
    if (type !== "warning" && type !== "error" && type !== "assert") return;
    const loc = msg.location();
    const sourceFile = sourceLabel(loc.url, loc.lineNumber, loc.columnNumber);
    const message = msg.text();
    push({
      kind: "console",
      level: type,
      message,
      sourceFile,
      url: loc.url || "",
      suggestedFix: suggestFix(message, sourceFile),
    });
  });

  page.on("pageerror", (err) => {
    const stackLine = (err.stack || "").split("\n").map((line) => line.trim()).find((line) => line.startsWith("at ")) || "";
    const message = err.message || String(err);
    push({
      kind: "pageerror",
      level: "error",
      message,
      sourceFile: stackLine || "(no stack)",
      url: stackLine,
      suggestedFix: suggestFix(message, stackLine),
    });
  });

  page.on("requestfailed", (req) => {
    const failure = req.failure();
    const message = `${req.method()} ${req.url()} — ${failure?.errorText || "request failed"}`;
    push({
      kind: "requestfailed",
      level: "error",
      message,
      sourceFile: req.url(),
      url: req.url(),
      suggestedFix: suggestFix(message, req.url()),
    });
  });

  page.on("response", (res) => {
    if (res.status() < 400) return;
    const url = res.url();
    if (url.startsWith("data:") || url.startsWith("chrome-extension:")) return;
    const message = `${res.status()} ${res.request().method()} ${url}`;
    push({
      kind: "http",
      level: res.status() >= 500 ? "error" : "warning",
      message,
      sourceFile: url,
      url,
      suggestedFix: suggestFix(message, url),
    });
  });

  const steps: StepRecord[] = [];

  return {
    setStep(name: string) {
      step = name;
    },
    noteScreenshot(name: string, screenshot: string) {
      const tagged = events.splice(0, events.length).map((event) => event);
      // Events collected since the previous screenshot belong to this step.
      // `step` is set by the caller before the action; we stamp it here.
      steps.push({
        step: name,
        screenshot,
        events: tagged.map((event) => ({ ...event, suggestedFix: event.suggestedFix })),
      });
      void step;
    },
    async collectA11y(pageForA11y: Page): Promise<A11yIssue[]> {
      return pageForA11y.evaluate(() => {
        const found: { message: string; sourceFile: string; suggestedFix: string }[] = [];
        document.querySelectorAll("button, a").forEach((el) => {
          const name = (el.getAttribute("aria-label") || el.textContent || "").trim();
          if (!name) {
            found.push({
              message: "Control without an accessible name",
              sourceFile: el.outerHTML.slice(0, 180),
              suggestedFix: "Give the control visible text or an aria-label.",
            });
          }
        });
        document.querySelectorAll("input, textarea, select").forEach((el) => {
          const id = el.getAttribute("id");
          const labelled =
            el.getAttribute("aria-label") ||
            el.getAttribute("aria-labelledby") ||
            (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) ||
            el.closest("label");
          if (!labelled) {
            found.push({
              message: "Field without a label",
              sourceFile: el.outerHTML.slice(0, 180),
              suggestedFix: "Wrap the field in a label or set aria-label.",
            });
          }
        });
        document.querySelectorAll("img").forEach((img) => {
          if (img.getAttribute("alt") == null) {
            found.push({
              message: "Image without an alt attribute",
              sourceFile: img.outerHTML.slice(0, 180),
              suggestedFix: "Set alt to a description, or alt=\"\" if the image is decorative.",
            });
          }
        });
        if (!document.documentElement.lang) {
          found.push({
            message: "html element has no lang",
            sourceFile: "bi-escales/frontend/index.html",
            suggestedFix: "Set lang on <html> and update it when the language switch changes.",
          });
        }
        const headings = [...document.querySelectorAll("h1, h2, h3, h4")].map((h) => Number(h.tagName.slice(1)));
        for (let i = 1; i < headings.length; i += 1) {
          if (headings[i] - headings[i - 1] > 1) {
            found.push({
              message: `Heading level jumps from h${headings[i - 1]} to h${headings[i]}`,
              sourceFile: "bi-escales/frontend/src/App.tsx",
              suggestedFix: "Do not skip heading levels. Keep one h1 and follow with h2 then h3.",
            });
            break;
          }
        }
        return found;
      });
    },
    steps,
  };
}

export type BrowserWatch = ReturnType<typeof attachBrowserWatch>;

export async function snap(page: Page, journey: string, step: string, watch: BrowserWatch): Promise<string> {
  const dir = path.join(shotsRoot, journey);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${step}.png`);
  await page.screenshot({ path: file, fullPage: true });
  watch.noteScreenshot(step, path.relative(root, file));
  return file;
}

export function writeJourneyReport(journey: string, watch: BrowserWatch, a11y: A11yIssue[]) {
  fs.mkdirSync(diagnosticsDir, { recursive: true });
  const current: DiagnosticsFile = fs.existsSync(diagnosticsJson)
    ? (JSON.parse(fs.readFileSync(diagnosticsJson, "utf8")) as DiagnosticsFile)
    : { viewport: "desktop 1440x900", journeys: [] };
  current.journeys = current.journeys.filter((item) => item.journey !== journey);
  current.journeys.push({ journey, steps: watch.steps, a11y });
  current.journeys.sort((a, b) => a.journey.localeCompare(b.journey));
  fs.writeFileSync(diagnosticsJson, JSON.stringify(current, null, 2));
  fs.writeFileSync(path.join(diagnosticsDir, "BROWSER-DIAGNOSTICS.md"), renderMarkdown(current));
}

function cell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").slice(0, 500);
}

function renderMarkdown(data: DiagnosticsFile): string {
  const lines: string[] = [
    "# Browser diagnostics",
    "",
    `Viewport: ${data.viewport}. Mobile viewports were not run.`,
    "",
    "Listeners: `console` (warning, error, assert), `pageerror`, `requestfailed`, and HTTP responses with status >= 400.",
    "Each step lists every event observed since the previous screenshot. An empty table means none were observed.",
    "",
  ];
  for (const journey of data.journeys) {
    lines.push(`## ${journey.journey}`, "");
    for (const step of journey.steps) {
      lines.push(`### ${step.step}`, "", `Screenshot: \`${step.screenshot}\``, "");
      lines.push("| Kind | Level | Message | Source file | Suggested fix |", "| --- | --- | --- | --- | --- |");
      if (step.events.length === 0) {
        lines.push("| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |");
      } else {
        for (const event of step.events) {
          lines.push(
            `| ${cell(event.kind)} | ${cell(event.level)} | ${cell(event.message)} | ${cell(event.sourceFile)} | ${cell(event.suggestedFix)} |`,
          );
        }
      }
      lines.push("");
    }
    lines.push("### Accessibility basics", "");
    if (journey.a11y.length === 0) {
      lines.push("No unlabeled controls, images missing alt, missing html lang, or skipped heading levels on the scanned screen.", "");
    } else {
      lines.push("| Message | Source | Suggested fix |", "| --- | --- | --- |");
      for (const issue of journey.a11y) {
        lines.push(`| ${cell(issue.message)} | ${cell(issue.sourceFile)} | ${cell(issue.suggestedFix)} |`);
      }
      lines.push("");
    }
  }
  return lines.join("\n");
}

export async function resetDemoLedger(request: import("@playwright/test").APIRequestContext) {
  const response = await request.post("http://127.0.0.1:8000/api/escales/demo/reset", {
    headers: { "x-admin-key": ADMIN_KEY },
  });
  if (!response.ok()) {
    throw new Error(`demo reset failed: ${response.status()} ${await response.text()}`);
  }
}

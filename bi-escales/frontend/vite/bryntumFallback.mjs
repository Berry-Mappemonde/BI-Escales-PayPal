/**
 * Build-time fallback for the optional Bryntum Scheduler trial.
 *
 * `@bryntum/scheduler` is an optionalDependency: npm may skip it (registry hiccup,
 * platform, licence). Rollup then fails on the dynamic import in BryntumTimeline and
 * the whole Render build breaks. When the package is missing, this plugin resolves
 * every `@bryntum/scheduler` import to a stub that throws at load time, so the lazy
 * import rejects and BryntumTimeline renders its plain-list fallback.
 */
import { createRequire } from "node:module";

const PACKAGE = "@bryntum/scheduler";
const STUB_JS = "\0bryntum-scheduler-missing.js";
const STUB_CSS = "\0bryntum-scheduler-missing.css";

export function bryntumInstalled(root = process.cwd()) {
  try {
    createRequire(`${root}/package.json`).resolve(`${PACKAGE}/package.json`);
    return true;
  } catch {
    return false;
  }
}

export function bryntumFallback({ isInstalled = bryntumInstalled, root } = {}) {
  let missing = null;
  return {
    name: "escales-bryntum-fallback",
    enforce: "pre",
    configResolved(config) {
      root = root || config.root;
    },
    resolveId(source) {
      if (source !== PACKAGE && !source.startsWith(`${PACKAGE}/`)) return null;
      if (missing === null) {
        missing = !isInstalled(root || process.cwd());
        if (missing) {
          console.warn(`[escales] ${PACKAGE} is not installed; the timeline uses its list fallback.`);
        }
      }
      if (!missing) return null;
      return source.endsWith(".css") ? STUB_CSS : STUB_JS;
    },
    load(id) {
      if (id === STUB_CSS) return "/* @bryntum/scheduler not installed */";
      if (id === STUB_JS) {
        return `throw new Error("${PACKAGE} is not installed (optional dependency)");`;
      }
      return null;
    },
  };
}

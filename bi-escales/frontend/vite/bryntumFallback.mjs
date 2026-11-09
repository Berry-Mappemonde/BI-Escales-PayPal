/**
 * Build-time fallback for optional Bryntum Scheduler Community packages.
 *
 * `@bryntum/scheduler-community` and `@bryntum/scheduler-react-community` are optionalDependencies:
 * npm may skip them (registry hiccup, platform). Rollup then fails on dynamic imports in
 * BryntumTimeline and the whole Render build breaks. When either package is missing, this plugin
 * resolves every matching import to a stub that throws at load time, so the lazy import rejects and
 * BryntumTimeline renders its plain-list fallback.
 */
import { createRequire } from "node:module";

const PACKAGES = ["@bryntum/scheduler-community", "@bryntum/scheduler-react-community"];
const STUB_JS = "\0bryntum-scheduler-missing.js";
const STUB_CSS = "\0bryntum-scheduler-missing.css";

function isBryntumImport(source) {
  return PACKAGES.some((pkg) => source === pkg || source.startsWith(`${pkg}/`));
}

export function bryntumInstalled(root = process.cwd()) {
  const req = createRequire(`${root}/package.json`);
  return PACKAGES.every((pkg) => {
    try {
      req.resolve(`${pkg}/package.json`);
      return true;
    } catch {
      return false;
    }
  });
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
      if (!isBryntumImport(source)) return null;
      if (missing === null) {
        missing = !isInstalled(root || process.cwd());
        if (missing) {
          console.warn(
            `[escales] Bryntum scheduler packages are not installed; the timeline uses its list fallback.`,
          );
        }
      }
      if (!missing) return null;
      return source.endsWith(".css") ? STUB_CSS : STUB_JS;
    },
    load(id) {
      if (id === STUB_CSS) return "/* @bryntum/scheduler-community not installed */";
      if (id === STUB_JS) {
        return `throw new Error("@bryntum/scheduler packages are not installed (optional dependency)");`;
      }
      return null;
    },
  };
}

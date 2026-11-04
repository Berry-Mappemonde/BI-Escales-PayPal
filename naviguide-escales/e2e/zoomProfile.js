// Profil CDP + longtask / écart de frame (méthode PROFIL_BUILD_PROD).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
export { dismissNotForNav } from "./helpers.js";

const here = dirname(fileURLToPath(import.meta.url));
export const AUDIT_DIR = join(here, "../../docs/audits");

export const ATLANTIC = { lat: 20, lon: -40, zoom: 3 };

export async function waitForMap(page) {
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 30_000 });
}

export async function setAtlanticView(page) {
  await page.evaluate(({ lat, lon, zoom }) => {
    const map = window.__naviguideScene.map;
    map.setView([lat, lon], zoom, { animate: false });
  }, ATLANTIC);
  await page.waitForTimeout(400);
}

export async function installObservers(page) {
  await page.evaluate(() => {
    window.__zoomLongTasks = [];
    window.__maxFrameGap = 0;
    window.__zoomProfiling = true;
    try {
      const obs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__zoomLongTasks.push({
            name: entry.name,
            duration: entry.duration,
            startTime: entry.startTime,
          });
        }
      });
      obs.observe({ type: "longtask", buffered: true });
      window.__zoomLtObs = obs;
    } catch {
      window.__zoomLtObs = null;
    }
    window.__zoomFramePrev = performance.now();
    window.__zoomMeasureFrom = performance.now();
    window.__maxSettledFrameGap = 0;
    const loop = (t) => {
      const gap = t - window.__zoomFramePrev;
      window.__zoomFramePrev = t;
      window.__maxFrameGap = Math.max(window.__maxFrameGap, gap);
      if (t >= window.__zoomMeasureFrom) {
        window.__maxSettledFrameGap = Math.max(window.__maxSettledFrameGap, gap);
      }
      if (window.__zoomProfiling) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });
}

export function summarizeCpuProfile(profile, topN = 12) {
  const nodes = profile?.nodes || [];
  const samples = profile?.samples || [];
  const timeDeltas = profile?.timeDeltas || [];
  const selfUs = new Map();
  if (samples.length && timeDeltas.length) {
    for (let i = 0; i < samples.length; i += 1) {
      const id = samples[i];
      const dt = timeDeltas[i] || 0;
      selfUs.set(id, (selfUs.get(id) || 0) + dt);
    }
  } else {
    for (const node of nodes) selfUs.set(node.id, (node.hitCount || 0) * 1000);
  }
  const byName = new Map();
  for (const node of nodes) {
    const name = node.callFrame?.functionName || "(anonymous)";
    const url = String(node.callFrame?.url || "");
    const file = url.split("/").pop() || "native";
    const key = `${name} @ ${file}`;
    byName.set(key, (byName.get(key) || 0) + (selfUs.get(node.id) || 0));
  }
  const rows = [...byName.entries()]
    .map(([name, us]) => ({ name, ms: Math.round((us / 1000) * 10) / 10 }))
    .sort((a, b) => b.ms - a.ms);
  const idle = rows.filter((row) => /idle|program|garbage/i.test(row.name));
  const work = rows.filter((row) => !/idle|program|garbage/i.test(row.name));
  return {
    top: work.slice(0, topN),
    idleMs: Math.round(idle.reduce((sum, row) => sum + row.ms, 0) * 10) / 10,
    workMs: Math.round(work.reduce((sum, row) => sum + row.ms, 0) * 10) / 10,
  };
}

export async function resetObservers(page) {
  await page.evaluate(() => {
    window.__zoomLongTasks = [];
    window.__maxFrameGap = 0;
    window.__maxSettledFrameGap = 0;
    window.__zoomFramePrev = performance.now();
    window.__zoomMeasureFrom = performance.now() + 80;
  });
}

export async function wheelNotches(page, count, { pauseMs = 90, deltaY = -120 } = {}) {
  const box = await page.locator(".leaflet-container").boundingBox();
  if (!box) throw new Error("carte absente");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await resetObservers(page);
  for (let i = 0; i < count; i += 1) {
    await page.mouse.wheel(0, deltaY);
    await page.waitForTimeout(pauseMs);
  }
}

export async function wheelForMs(page, durationMs, { stepMs = 180 } = {}) {
  const box = await page.locator(".leaflet-container").boundingBox();
  if (!box) throw new Error("carte absente");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await resetObservers(page);
  const started = Date.now();
  let inward = true;
  while (Date.now() - started < durationMs) {
    await page.mouse.wheel(0, inward ? -120 : 120);
    inward = !inward;
    await page.waitForTimeout(stepMs);
  }
}

export async function collectObservers(page) {
  return page.evaluate(() => {
    window.__zoomProfiling = false;
    const tasks = window.__zoomLongTasks || [];
    const maxLongTask = tasks.reduce((max, entry) => Math.max(max, entry.duration || 0), 0);
    return {
      longTasks: tasks,
      maxLongTask,
      maxFrameGap: window.__maxFrameGap || 0,
      maxSettledFrameGap: window.__maxSettledFrameGap || 0,
    };
  });
}

/** Plus longue rafale occupée du profil CDP (hors idle / program / GC). */
export function longestBusyStreakMs(profile) {
  const nodes = profile?.nodes || [];
  const samples = profile?.samples || [];
  const timeDeltas = profile?.timeDeltas || [];
  const idleIds = new Set();
  for (const node of nodes) {
    const name = node.callFrame?.functionName || "";
    if (/\(idle\)|\(program\)|\(garbage collector\)/i.test(name)) idleIds.add(node.id);
  }
  let max = 0;
  let cur = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const dt = (timeDeltas[i] || 0) / 1000;
    if (idleIds.has(samples[i])) {
      max = Math.max(max, cur);
      cur = 0;
    } else {
      cur += dt;
    }
  }
  return Math.max(max, cur);
}

export function longestMeasuredMs(observed) {
  if (observed.maxLongTask > 0) return observed.maxLongTask;
  return observed.maxSettledFrameGap || observed.maxFrameGap;
}

export function writeProfileJson(phase, payload) {
  mkdirSync(AUDIT_DIR, { recursive: true });
  const dest = join(AUDIT_DIR, `zoom-profile-${phase}.json`);
  writeFileSync(dest, `${JSON.stringify(payload, null, 2)}\n`);
  return dest;
}

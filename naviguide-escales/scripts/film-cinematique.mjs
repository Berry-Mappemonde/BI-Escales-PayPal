// Mesure de la cinématique du film (sans voix : horloge murale). Usage, depuis naviguide-simulator/ :
//   node scripts/film-cinematique.mjs http://localhost:5174/?view=suivre 45
//   node scripts/film-cinematique.mjs http://127.0.0.1:5199/ 3 --video /tmp/film.mov --video-only
// L'enregistrement (ou le premier cliché conservé) commence après [data-testid="app-ready"],
// ou à défaut après map.loaded(). Aucune image blanche en tête. Le titre du document reste.
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { arch, cpus, platform, release, tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { inflateSync } from "node:zlib";

// Playwright choisit le binaire au chargement du module. Sur Apple Silicon, une
// liste de processeurs vide le fait chercher la build x64 : on corrige avant l'import.
function ensurePlaywrightEnv() {
  if (platform() === "darwin" && arch() === "arm64" && !process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE) {
    const apple = cpus().some((cpu) => String(cpu.model || "").includes("Apple"));
    if (!apple) {
      const major = Number(String(release()).split(".")[0]) || 25;
      const macVersion = major >= 25 ? 26 : major >= 20 ? 11 + (major - 20) : 11;
      process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE = `mac${macVersion}-arm64`;
    }
  }
  const browsers = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!browsers) return;
  let hasChromium = false;
  try {
    hasChromium = existsSync(browsers) && readdirSync(browsers).some((name) => name.startsWith("chromium"));
  } catch {
    hasChromium = false;
  }
  if (!hasChromium) delete process.env.PLAYWRIGHT_BROWSERS_PATH;
}

let chromiumPromise;
function playwrightChromium() {
  ensurePlaywrightEnv();
  if (!chromiumPromise) chromiumPromise = import("playwright").then((mod) => mod.chromium);
  return chromiumPromise;
}

const RELAXED_LAUNCH_ARGS = ["--no-sandbox", "--disable-gpu", "--single-process", "--no-zygote"];

/** Une page blanche : luminance moyenne au-dessus de 250 et variance proche de 0. */
export const BLANK_MEAN_ABOVE = 250;
export const BLANK_VARIANCE_BELOW = 16;

const CAPTURE_FRAMES = 6;
const CAPTURE_INTERVAL_MS = 500;
const CAPTURE_FPS = 2;

export function isBlankWhiteFrame(mean, variance) {
  return Number(mean) > BLANK_MEAN_ABOVE && Number(variance) < BLANK_VARIANCE_BELOW;
}

export function luminanceStats(pixels, channels = 4) {
  const n = Math.floor(pixels.length / channels);
  if (!n) throw new Error("image vide");
  let sum = 0;
  let sumSq = 0;
  for (let i = 0, p = 0; i < n; i += 1, p += channels) {
    const y = 0.2126 * pixels[p] + 0.7152 * pixels[p + 1] + 0.0722 * pixels[p + 2];
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / n;
  const variance = Math.max(0, sumSq / n - mean * mean);
  return { mean, variance, n };
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

export function decodePngRgba(buf) {
  const png = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (png.length < 8 || !png.subarray(0, 8).equals(sig)) throw new Error("png illisible");
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let interlace = 0;
  const idat = [];
  while (offset + 8 <= png.length) {
    const len = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    const start = offset + 8;
    const end = start + len;
    if (end + 4 > png.length) throw new Error("png tronqué");
    const data = png.subarray(start, end);
    offset = end + 4;
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") break;
  }
  if (!width || !height) throw new Error("png sans en-tête");
  if (bitDepth !== 8 || interlace !== 0) {
    throw new Error(`png non pris en charge (${bitDepth}/${colorType}/${interlace})`);
  }
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : 0;
  if (!channels) throw new Error(`png couleur ${colorType}`);
  const inflated = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const need = height * (stride + 1);
  if (inflated.length < need) throw new Error(`png incomplet ${inflated.length} < ${need}`);
  const out = new Uint8Array(width * height * 4);
  let src = 0;
  let prev = new Uint8Array(stride);
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[src];
    src += 1;
    const row = inflated.subarray(src, src + stride);
    src += stride;
    const recon = new Uint8Array(stride);
    for (let i = 0; i < stride; i += 1) {
      const left = i >= channels ? recon[i - channels] : 0;
      const up = prev[i];
      const ul = i >= channels ? prev[i - channels] : 0;
      const x = row[i];
      let v = x;
      if (filter === 1) v = (x + left) & 255;
      else if (filter === 2) v = (x + up) & 255;
      else if (filter === 3) v = (x + Math.floor((left + up) / 2)) & 255;
      else if (filter === 4) v = (x + paeth(left, up, ul)) & 255;
      else if (filter !== 0) throw new Error(`filtre png ${filter}`);
      recon[i] = v;
    }
    prev = recon;
    for (let x = 0; x < width; x += 1) {
      const o = (y * width + x) * 4;
      if (channels === 4) {
        out[o] = recon[x * 4];
        out[o + 1] = recon[x * 4 + 1];
        out[o + 2] = recon[x * 4 + 2];
        out[o + 3] = recon[x * 4 + 3];
      } else if (channels === 3) {
        out[o] = recon[x * 3];
        out[o + 1] = recon[x * 3 + 1];
        out[o + 2] = recon[x * 3 + 2];
        out[o + 3] = 255;
      } else {
        out[o] = recon[x];
        out[o + 1] = recon[x];
        out[o + 2] = recon[x];
        out[o + 3] = 255;
      }
    }
  }
  return out;
}

export function luminanceOfPng(buf) {
  return luminanceStats(decodePngRgba(buf), 4);
}

function assertNotBlankUrl(url) {
  if (!url || url === "about:blank" || url.startsWith("about:")) {
    throw new Error("la capture est encore sur about:blank");
  }
}

function assertTitleKept(before, after) {
  const next = (after || "").trim();
  if (!next || /^about:blank$/i.test(next)) throw new Error("titre du document absent");
  const prev = (before || "").trim();
  if (prev && !/^about:blank$/i.test(prev) && next !== prev) {
    throw new Error(`titre du document modifié (« ${prev} » → « ${next} »)`);
  }
}

export async function launchCaptureBrowser() {
  const chromium = await playwrightChromium();
  const attempts = [
    { headless: true },
    { headless: true, args: RELAXED_LAUNCH_ARGS },
    { headless: true, channel: "chrome" },
    { headless: true, channel: "chrome", args: RELAXED_LAUNCH_ARGS },
  ];
  const errors = [];
  for (const opts of attempts) {
    try {
      return await chromium.launch(opts);
    } catch (err) {
      errors.push(err instanceof Error ? err.message.split("\n")[0] : String(err));
    }
  }
  throw new Error(`navigateur indisponible : ${errors.join(" | ")}`);
}

/**
 * Attend l'application peinte. Le titre lu au début doit être encore là.
 * @returns {{ via: "app-ready" | "map.loaded", title: string }}
 */
export async function waitForCaptureStart(page, {
  timeout = 60_000,
  readyTimeout = 8_000,
} = {}) {
  assertNotBlankUrl(page.url());
  const titleBefore = await page.title();
  const ready = await page.waitForSelector('[data-testid="app-ready"]', {
    state: "attached",
    timeout: readyTimeout,
  }).then(() => true).catch(() => false);
  if (!ready) {
    await page.waitForFunction(() => {
      const map = window.__naviguideScene && window.__naviguideScene.map;
      if (!map) return false;
      if (typeof map.loaded === "function") return map.loaded() === true;
      return true;
    }, null, { timeout });
  }
  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
  assertNotBlankUrl(page.url());
  const title = await page.title();
  assertTitleKept(titleBefore, title);
  const stillThere = await page.evaluate(() => {
    const el = document.querySelector("title");
    const text = (el?.textContent || "").trim();
    return Boolean(el && el.isConnected && text && !/^about:blank$/i.test(text));
  });
  if (!stillThere) throw new Error("titre du document absent");
  return { via: ready ? "app-ready" : "map.loaded", title };
}

async function takeKeptFrames(page, { frames, intervalMs, blankBudgetMs }) {
  const kept = [];
  const t0 = Date.now();
  let dropped = 0;
  while (kept.length < frames) {
    const buf = await page.screenshot({ type: "png" });
    const stats = luminanceOfPng(buf);
    const blank = isBlankWhiteFrame(stats.mean, stats.variance);
    if (blank && kept.length === 0) {
      dropped += 1;
      if (Date.now() - t0 > blankBudgetMs) {
        throw new Error(`image blanche (moyenne ${stats.mean.toFixed(1)}, variance ${stats.variance.toFixed(2)})`);
      }
      await page.waitForTimeout(50);
      continue;
    }
    if (blank) {
      throw new Error(`image blanche dans la capture (image ${kept.length + 1}, moyenne ${stats.mean.toFixed(1)})`);
    }
    kept.push(buf);
    if (kept.length < frames) await page.waitForTimeout(intervalMs);
  }
  return { kept, dropped };
}

/** Premier cliché non blanc, après l'application prête. */
export async function captureFirstFrame(page, opts = {}) {
  const started = await waitForCaptureStart(page, opts);
  const { kept } = await takeKeptFrames(page, {
    frames: 1,
    intervalMs: opts.intervalMs ?? 0,
    blankBudgetMs: opts.blankBudgetMs ?? 4_000,
  });
  const title = await page.title();
  assertTitleKept(started.title, title);
  return { ...started, title, png: kept[0], stats: luminanceOfPng(kept[0]) };
}

export function hasFfmpeg() {
  const bin = spawnSync("ffmpeg", ["-version"], { encoding: "utf8" });
  const probe = spawnSync("ffprobe", ["-version"], { encoding: "utf8" });
  return bin.status === 0 && probe.status === 0;
}

export function encodeFramesToVideo(frames, outPath, fps = CAPTURE_FPS) {
  if (!hasFfmpeg()) throw new Error("ffmpeg absent");
  const dir = mkdtempSync(join(tmpdir(), "film-cap-"));
  try {
    frames.forEach((buf, i) => {
      writeFileSync(join(dir, `f${String(i).padStart(3, "0")}.png`), buf);
    });
    const proc = spawnSync("ffmpeg", [
      "-y", "-loglevel", "error",
      "-framerate", String(fps),
      "-i", join(dir, "f%03d.png"),
      "-c:v", "png",
      "-pix_fmt", "rgb24",
      outPath,
    ], { encoding: "utf8" });
    if (proc.status !== 0) throw new Error((proc.stderr || `ffmpeg ${proc.status}`).slice(-600));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  return outPath;
}

export function extractVideoFrames(videoPath, { seconds = 3 } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "film-ex-"));
  try {
    const proc = spawnSync("ffmpeg", [
      "-y", "-loglevel", "error",
      "-t", String(seconds),
      "-i", videoPath,
      join(dir, "e%03d.png"),
    ], { encoding: "utf8" });
    if (proc.status !== 0) throw new Error((proc.stderr || `ffmpeg ${proc.status}`).slice(-600));
    return readdirSync(dir).filter((name) => name.endsWith(".png")).sort()
      .map((name) => readFileSync(join(dir, name)));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

export function videoDurationSeconds(videoPath) {
  const proc = spawnSync("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "csv=p=0",
    videoPath,
  ], { encoding: "utf8" });
  if (proc.status !== 0) throw new Error((proc.stderr || "ffprobe").slice(-400));
  return Number(String(proc.stdout || "").trim());
}

/**
 * Enregistre après l'application peinte. Les images blanches de tête sont écartées.
 * @returns {{ via: string, title: string, frames: Buffer[], dropped: number }}
 */
export async function recordAfterReady(page, {
  outPath,
  frames = CAPTURE_FRAMES,
  intervalMs = CAPTURE_INTERVAL_MS,
  readyTimeout = 8_000,
  timeout = 60_000,
  blankBudgetMs = 4_000,
} = {}) {
  const started = await waitForCaptureStart(page, { timeout, readyTimeout });
  const { kept, dropped } = await takeKeptFrames(page, { frames, intervalMs, blankBudgetMs });
  const title = await page.title();
  assertTitleKept(started.title, title);
  if (outPath) encodeFramesToVideo(kept, outPath);
  return { ...started, title, frames: kept, dropped };
}

export async function runReadyRecording({
  url,
  outPath,
  frames = CAPTURE_FRAMES,
  intervalMs = CAPTURE_INTERVAL_MS,
  readyTimeout = 8_000,
  timeout = 60_000,
  blankBudgetMs = 4_000,
  viewport = { width: 640, height: 360 },
} = {}) {
  const browser = await launchCaptureBrowser();
  try {
    const page = await browser.newPage({ viewport });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout });
    return await recordAfterReady(page, {
      outPath, frames, intervalMs, readyTimeout, timeout, blankBudgetMs,
    });
  } finally {
    await browser.close();
  }
}

export function parseArgs(argv) {
  const rest = [];
  let videoPath = "";
  let videoOnly = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--video") {
      videoPath = argv[i + 1] || "";
      i += 1;
    } else if (argv[i] === "--video-only") {
      videoOnly = true;
    } else {
      rest.push(argv[i]);
    }
  }
  return {
    url: rest[0] || "http://localhost:5174/?view=suivre",
    seconds: Number(rest[1] || 45),
    videoPath,
    videoOnly,
  };
}

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  return import.meta.url === pathToFileURL(entry).href;
}

async function main() {
  const { url, seconds, videoPath, videoOnly } = parseArgs(process.argv.slice(2));
  const browser = await launchCaptureBrowser();
  let data = null;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 860 } });
    page.on("pageerror", (e) => console.log("pageerror:", String(e).slice(0, 200)));
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
    if (videoPath || videoOnly) {
      const clip = await recordAfterReady(page, { outPath: videoPath || undefined });
      console.log(`capture: ${clip.via}`);
      if (videoPath) console.log(`video: ${videoPath}`);
      if (videoOnly) return;
    } else {
      const start = await waitForCaptureStart(page);
      console.log(`capture: ${start.via}`);
    }
    await page.waitForTimeout(6000);
    const clicked = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((b) => /Revoir/.test(b.textContent || ""));
      if (!btn) return false;
      btn.click();
      return true;
    });
    if (!clicked) {
      console.log("pas de bouton Revoir");
      process.exitCode = 1;
      return;
    }

    data = await page.evaluate((secs) => new Promise((resolve) => {
      const s = window.__naviguideScene;
      const map = s.map;
      const out = [];
      const t0 = performance.now();
      let prev = t0;
      const tick = (now) => {
        const f = window.__naviguideFilm || {};
        const boat = document.querySelector(".catamaran-divicon--live");
        let bx = null; let by = null;
        if (boat) { const r = boat.getBoundingClientRect(); bx = r.left + r.width / 2; by = r.top + r.height / 2; }
        const c = map.getCenter();
        out.push({
          t: now - t0, dt: now - prev,
          tMs: f.tMs ?? null, ch: f.chapterIdx ?? null, charIdx: f.charIdx ?? null,
          lat: f.lat ?? null, lon: f.lon ?? null,
          bx, by, cLat: c.lat, cLng: c.lng, zoom: map.getZoom(),
        });
        prev = now;
        if (now - t0 < secs * 1000) requestAnimationFrame(tick); else resolve(out);
      };
      requestAnimationFrame(tick);
    }), seconds);

    await page.screenshot({ path: "/tmp/film-cinematique.png" });
  } finally {
    await browser.close();
  }
  if (!data) return;

  // ---- statistiques
  const frames = data.slice(1);
  const dts = frames.map((r) => r.dt);
  const q = (arr, p) => { const a = [...arr].sort((x, y) => x - y); return a[Math.min(a.length - 1, Math.floor(p * a.length))]; };
  const long = dts.filter((d) => d > 34).length;
  console.log(`frames: ${frames.length} sur ${seconds}s → ${(frames.length / seconds).toFixed(1)} fps ; dt médian ${q(dts, 0.5).toFixed(1)} ms, p95 ${q(dts, 0.95).toFixed(1)} ms, max ${Math.max(...dts).toFixed(0)} ms ; frames > 34 ms : ${long} (${(100 * long / frames.length).toFixed(1)} %)`);

  // déplacement du bateau à l'écran par frame (hors changements de zoom)
  const moves = [];
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1]; const b = frames[i];
    if (a.bx == null || b.bx == null || a.zoom !== b.zoom) continue;
    moves.push(Math.hypot(b.bx - a.bx, b.by - a.by));
  }
  const zero = moves.filter((m) => m < 0.05).length;
  console.log(`bateau à l'écran : ${moves.length} pas ; nuls (< 0,05 px) ${zero} (${(100 * zero / moves.length).toFixed(1)} %) ; médiane ${q(moves, 0.5).toFixed(2)} px, p90 ${q(moves, 0.9).toFixed(2)} px, p99 ${q(moves, 0.99).toFixed(2)} px, max ${Math.max(...moves).toFixed(1)} px`);

  // pan caméra par frame (px) hors zoom
  const pans = [];
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1]; const b = frames[i];
    if (a.zoom !== b.zoom) continue;
    const scale = 256 * 2 ** b.zoom / 360;
    pans.push(Math.hypot((b.cLng - a.cLng) * scale, (b.cLat - a.cLat) * scale));
  }
  const pz = pans.filter((m) => m < 0.05).length;
  console.log(`caméra : pas nuls ${pz} (${(100 * pz / pans.length).toFixed(1)} %) ; médiane ${q(pans, 0.5).toFixed(2)} px, p90 ${q(pans, 0.9).toFixed(2)} px, max ${Math.max(...pans).toFixed(1)} px ; changements de zoom : ${frames.filter((r, i) => i && r.zoom !== frames[i - 1].zoom).length}`);

  // vitesse du temps-film (heures de film par seconde murale), par fenêtre de 1 s
  const speeds = [];
  for (let i = 60; i < frames.length; i += 60) {
    const a = frames[i - 60]; const b = frames[i];
    if (a.tMs == null || b.tMs == null || b.t === a.t) continue;
    speeds.push({ t: (b.t / 1000).toFixed(0), hPerS: ((b.tMs - a.tMs) / 3600000) / ((b.t - a.t) / 1000), ch: b.ch, charIdx: Math.round(b.charIdx) });
  }
  console.log("vitesse temps-film (h de voyage par seconde), par seconde :");
  console.log(speeds.map((s) => `${s.t}s:ch${s.ch}@${s.charIdx}=${s.hPerS.toFixed(1)}h/s`).join("  "));
  // sauts de temps-film entre deux frames
  const jumps = [];
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1]; const b = frames[i];
    if (a.tMs == null || b.tMs == null) continue;
    jumps.push((b.tMs - a.tMs) / 3600000);
  }
  console.log(`saut de temps-film par frame : médiane ${q(jumps, 0.5).toFixed(2)} h, p99 ${q(jumps, 0.99).toFixed(1)} h, max ${Math.max(...jumps).toFixed(1)} h ; frames sans avance ${jumps.filter((j) => j <= 0).length}`);
}

if (invokedDirectly()) {
  main().catch((err) => {
    console.error(err instanceof Error ? err.message : err);
    process.exitCode = 1;
  });
}

import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deflateSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import {
  BLANK_MEAN_ABOVE,
  BLANK_VARIANCE_BELOW,
  extractVideoFrames,
  hasFfmpeg,
  isBlankWhiteFrame,
  luminanceOfPng,
  luminanceStats,
  recordAfterReady,
  runReadyRecording,
  videoDurationSeconds,
  launchCaptureBrowser,
} from "./film-cinematique.mjs";

function crc32(buf) {
  let c = ~0;
  for (const b of buf) {
    c ^= b;
    for (let i = 0; i < 8; i += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}

function pngChunk(type, data) {
  const body = Buffer.concat([Buffer.from(type), data]);
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function solidPng(width, height, rgba) {
  const row = Buffer.alloc(1 + width * 4);
  for (let x = 0; x < width; x += 1) rgba.copy(row, 1 + x * 4);
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  return Buffer.concat([
    sig,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function pageHtml({ paintMs, marker, retitle = false, dark = true }) {
  const color = dark ? "#0f172a" : "#ffffff";
  const markerJs = marker === "app-ready" || marker === "white"
    ? 'stage.setAttribute("data-testid", "app-ready");'
    : "";
  const mapJs = marker === "map"
    ? "window.__naviguideScene = { map: { loaded() { return true; } } };"
    : "";
  const titleJs = retitle ? 'document.title = "autre";' : "";
  return `<!DOCTYPE html><html><head><title>NAVIGUIDE simulator</title>
<style>html,body{margin:0;height:100%;background:#fff}</style></head>
<body><div id="stage" style="position:fixed;inset:0;background:#ffffff"></div>
<script>
  window.__phase = "blank";
  setTimeout(() => {
    ${titleJs}
    const stage = document.getElementById("stage");
    stage.style.background = "${color}";
    ${markerJs}
    ${mapJs}
    window.__phase = "ready";
  }, ${paintMs});
</script></body></html>`;
}

function startServer() {
  const server = createServer((req, res) => {
    const path = req.url || "/";
    let body;
    if (path.startsWith("/map")) body = pageHtml({ paintMs: 400, marker: "map" });
    else if (path.startsWith("/white")) body = pageHtml({ paintMs: 0, marker: "white", dark: false });
    else if (path.startsWith("/retitle")) body = pageHtml({ paintMs: 800, marker: "app-ready", retitle: true });
    else body = pageHtml({ paintMs: 1600, marker: "app-ready" });
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
    res.end(body);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        server,
        origin: `http://127.0.0.1:${port}`,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

function runCli(args) {
  const script = fileURLToPath(new URL("./film-cinematique.mjs", import.meta.url));
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], {
      env: { ...process.env, NAVIGUIDE_LLM_MODE: "off" },
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk) => { out += chunk; });
    child.stderr.on("data", (chunk) => { err += chunk; });
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`timeout CLI\n${out}\n${err}`));
    }, 40_000);
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, out, err });
    });
  });
}

describe("luminance d'une image", () => {
  it("reconnaît un aplat blanc et refuse un aplat mer", () => {
    const white = solidPng(8, 8, Buffer.from([255, 255, 255, 255]));
    const sea = solidPng(8, 8, Buffer.from([15, 23, 42, 255]));
    const w = luminanceOfPng(white);
    const s = luminanceOfPng(sea);
    assert.ok(w.mean > BLANK_MEAN_ABOVE, String(w.mean));
    assert.ok(w.variance < BLANK_VARIANCE_BELOW, String(w.variance));
    assert.equal(isBlankWhiteFrame(w.mean, w.variance), true);
    assert.equal(isBlankWhiteFrame(s.mean, s.variance), false);
    assert.equal(isBlankWhiteFrame(BLANK_MEAN_ABOVE, 0), false);
    assert.equal(isBlankWhiteFrame(255, BLANK_VARIANCE_BELOW), false);
    const raw = new Uint8Array([255, 255, 255, 255]);
    assert.ok(luminanceStats(raw, 4).mean > 250);
  });
});

describe("capture après l'application", { timeout: 90_000 }, () => {
  it("serveur factice : pas d'image blanche, titre conservé, repli carte", async () => {
    const fake = await startServer();
    let browser;
    try {
      browser = await launchCaptureBrowser();
    } catch (err) {
      await fake.close();
      throw err;
    }
    const dir = mkdtempSync(join(tmpdir(), "film-cli-"));
    const videoPath = join(dir, "capture.mov");
    try {
      const page = await browser.newPage({ viewport: { width: 320, height: 180 } });
      await page.goto(`${fake.origin}/`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(120);
      const early = luminanceOfPng(await page.screenshot({ type: "png" }));
      assert.equal(isBlankWhiteFrame(early.mean, early.variance), true, JSON.stringify(early));
      assert.equal(await page.title(), "NAVIGUIDE simulator");

      const clip = await runReadyRecording({
        url: `${fake.origin}/`,
        viewport: { width: 320, height: 180 },
        readyTimeout: 8_000,
      });
      assert.equal(clip.via, "app-ready");
      assert.equal(clip.title, "NAVIGUIDE simulator");
      assert.ok(clip.frames.length >= 6);
      for (const frame of clip.frames) {
        const stats = luminanceOfPng(frame);
        assert.equal(isBlankWhiteFrame(stats.mean, stats.variance), false, JSON.stringify(stats));
        assert.ok(stats.mean < 80, `luminance ${stats.mean}`);
      }

      const mapClip = await runReadyRecording({
        url: `${fake.origin}/map`,
        viewport: { width: 320, height: 180 },
        readyTimeout: 250,
        frames: 2,
        intervalMs: 40,
      });
      assert.equal(mapClip.via, "map.loaded");
      assert.equal(mapClip.title, "NAVIGUIDE simulator");
      for (const frame of mapClip.frames) {
        const stats = luminanceOfPng(frame);
        assert.equal(isBlankWhiteFrame(stats.mean, stats.variance), false, JSON.stringify(stats));
      }

      await page.goto(`${fake.origin}/white`, { waitUntil: "domcontentloaded" });
      const whiteShot = luminanceOfPng(await page.screenshot({ type: "png" }));
      assert.equal(isBlankWhiteFrame(whiteShot.mean, whiteShot.variance), true, JSON.stringify(whiteShot));
      await assert.rejects(
        () => recordAfterReady(page, { blankBudgetMs: 350, readyTimeout: 1_000, frames: 2, intervalMs: 20 }),
        /image blanche/,
      );

      await page.goto(`${fake.origin}/retitle`, { waitUntil: "domcontentloaded" });
      await assert.rejects(
        () => recordAfterReady(page, { readyTimeout: 3_000, frames: 1, blankBudgetMs: 1_000 }),
        /titre du document modifié/,
      );

      const cliArgs = hasFfmpeg()
        ? [`${fake.origin}/`, "3", "--video", videoPath, "--video-only"]
        : [`${fake.origin}/`, "3", "--video-only"];
      const cli = await runCli(cliArgs);
      assert.equal(cli.code, 0, `${cli.out}\n${cli.err}`);
      assert.match(cli.out, /capture: app-ready/);
      assert.doesNotMatch(cli.out, /about:blank/);
      if (hasFfmpeg()) {
        assert.match(cli.out, /video:/);
        const duration = videoDurationSeconds(videoPath);
        assert.ok(duration >= 2.5, `durée ${duration}`);
        const extracted = extractVideoFrames(videoPath, { seconds: 3 });
        assert.ok(extracted.length >= 4, `images ${extracted.length}`);
        for (const frame of extracted) {
          const stats = luminanceOfPng(frame);
          assert.equal(isBlankWhiteFrame(stats.mean, stats.variance), false, JSON.stringify(stats));
          assert.ok(stats.mean < 80, `vidéo luminance ${stats.mean}`);
        }
      }
    } finally {
      await browser.close();
      await fake.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

import { atlanticSpanNm, playheadOnPlay } from "../engine/routePlayhead.js";
import { airHopSeconds, nmPerSecond } from "../engine/playSpeeds.js";
import { edgeAtFilmNm, filmLength } from "../engine/filmCast.js";
import { dwellMsForProfile, shouldPauseAtStop, stepPlayback } from "../engine/stationDwell.js";

const SCENE_INTERVAL_MS = 125;
const HUD_INTERVAL_MS = 250;

function frameIntervalMs(config) {
  return config?.filmActive ? 0 : SCENE_INTERVAL_MS;
}

function playheadLength(flat) {
  return filmLength(flat) || flat?.totalNm || 0;
}

function rateAtPlayhead(flat, filmNm, sailRate, profile) {
  const edge = edgeAtFilmNm(flat, filmNm);
  if (edge?.jump) {
    const span = Math.max(1e-6, edge.filmSpan);
    return span / airHopSeconds(profile);
  }
  return sailRate;
}

function asStations(marks) {
  return (marks || []).map((mark) => ({
    filmNm: mark.filmNm ?? mark.nm,
    nm: mark.nm,
    name: mark.name,
    kind: mark.kind,
  }));
}

/**
 * Imperative requestAnimationFrame playhead.
 *
 * `onFrame` is for Leaflet and never triggers React. `onPublish` is bounded
 * to the HUD cadence, with immediate publications for direct user commands.
 */
export class ScenePlaybackController {
  constructor({
    onFrame = () => {},
    onPublish = () => {},
    requestFrame = globalThis.requestAnimationFrame?.bind(globalThis),
    cancelFrame = globalThis.cancelAnimationFrame?.bind(globalThis),
  } = {}) {
    this.onFrame = onFrame;
    this.onPublish = onPublish;
    this.requestFrame = requestFrame;
    this.cancelFrame = cancelFrame;
    this.config = { flat: null, marks: [], boatKnots: 0, enabled: false, stopAuto: false, filmActive: false };
    this.state = {
      nm: 0,
      playing: false,
      profile: "normal",
      jumpToken: 0,
      holdingStation: null,
    };
    this.dwellMsLeft = 0;
    this.skipDwell = false;
    this.lastTs = 0;
    this.lastAir = false;
    this.lastFrameAt = -Infinity;
    this.lastPublishAt = -Infinity;
    this.raf = null;
  }

  snapshot() {
    const { flat, marks, boatKnots } = this.config;
    const totalNm = playheadLength(flat);
    const atlanticNm = atlanticSpanNm(marks, flat?.totalNm || totalNm);
    return {
      ...this.state,
      totalNm,
      atlanticNm,
      rate: nmPerSecond(this.state.profile, { boatKnots, atlanticNm }),
      sailTotalNm: flat?.totalNm || 0,
      holding: Boolean(this.state.holdingStation),
    };
  }

  configure(nextConfig) {
    const previousFlat = this.config.flat;
    this.config = { ...this.config, ...nextConfig };
    const total = playheadLength(this.config.flat);
    if (this.state.nm > total) this.state.nm = total;
    if (!this.config.enabled && this.state.playing) {
      this.state.playing = false;
      this.dwellMsLeft = 0;
      this.state.holdingStation = null;
      this.stopLoop();
    }
    if (previousFlat !== this.config.flat) {
      this.dwellMsLeft = 0;
      this.state.holdingStation = null;
    }
    this.emitFrame(true);
    this.publish(true);
  }

  setProfile(profile) {
    this.state.profile = profile || "normal";
    this.emitFrame(true);
    this.publish(true);
  }

  play() {
    if (!this.config.enabled) return;
    this.state.playing = true;
    this.startLoop();
    this.publish(true);
  }

  pause() {
    this.state.playing = false;
    this.dwellMsLeft = 0;
    this.state.holdingStation = null;
    this.stopLoop();
    this.emitFrame(true);
    this.publish(true);
  }

  toggle() {
    if (this.state.playing) {
      this.pause();
      return;
    }
    const total = playheadLength(this.config.flat);
    const next = playheadOnPlay(this.state.nm, total);
    if (next !== this.state.nm) {
      this.state.nm = next;
      this.dwellMsLeft = 0;
      this.state.holdingStation = null;
      this.skipDwell = true;
      this.state.jumpToken += 1;
      this.emitFrame(true);
    }
    this.play();
  }

  seek(nextNm, { play = false, jump = false } = {}) {
    const total = playheadLength(this.config.flat);
    this.state.nm = Math.max(0, Math.min(total, Number(nextNm) || 0));
    this.dwellMsLeft = 0;
    this.state.holdingStation = null;
    if (jump) {
      this.skipDwell = true;
      this.state.jumpToken += 1;
    }
    if (play) this.state.playing = true;
    this.emitFrame(true);
    this.publish(true);
    if (this.state.playing) this.startLoop();
  }

  startLoop() {
    if (this.raf || !this.requestFrame || !this.config.enabled || !this.state.playing) return;
    this.raf = this.requestFrame((ts) => this.step(ts));
  }

  stopLoop() {
    if (this.raf != null && this.cancelFrame) this.cancelFrame(this.raf);
    this.raf = null;
    this.lastTs = 0;
  }

  step(ts) {
    this.raf = null;
    if (!this.config.enabled || !this.state.playing) {
      this.lastTs = 0;
      return;
    }
    if (!this.lastTs) this.lastTs = ts;
    const dt = Math.min(0.08, (ts - this.lastTs) / 1000);
    this.lastTs = ts;
    const { flat, marks, boatKnots, stopAuto } = this.config;
    const total = playheadLength(flat);
    const atlanticNm = atlanticSpanNm(marks, flat?.totalNm || total);
    const sailRate = nmPerSecond(this.state.profile, { boatKnots, atlanticNm });
    const rate = rateAtPlayhead(flat, this.state.nm, sailRate, this.state.profile);
    const inAir = Boolean(edgeAtFilmNm(flat, this.state.nm)?.jump);
    if (inAir !== this.lastAir) {
      this.lastAir = inAir;
      this.state.jumpToken += 1;
    }
    const stepped = stepPlayback({
      filmNm: this.state.nm,
      dwellMsLeft: this.dwellMsLeft,
      deltaMs: dt * 1000,
      rate,
      stations: asStations(marks),
      maxFilmNm: total,
      dwellMs: stopAuto ? 0 : dwellMsForProfile(this.state.profile),
      jump: this.skipDwell,
    });
    this.skipDwell = false;
    this.dwellMsLeft = stepped.dwellMsLeft;
    this.state.nm = stepped.filmNm;
    if (shouldPauseAtStop(stopAuto, stepped.arrived)) {
      this.state.playing = false;
      this.state.holdingStation = stepped.arrived;
      this.emitFrame(true);
      this.publish(true);
      return;
    }
    this.state.holdingStation = stepped.arrived || (stepped.holding ? this.state.holdingStation : null);
    this.emitFrame(false, ts);
    this.publish(false, ts);
    if (this.state.nm >= total && !stepped.holding) {
      this.state.playing = false;
      this.state.holdingStation = null;
      this.emitFrame(true, ts);
      this.publish(true, ts);
      return;
    }
    this.startLoop();
  }

  emitFrame(force = false, now = performance.now()) {
    if (!force && now - this.lastFrameAt < frameIntervalMs(this.config)) return;
    this.lastFrameAt = now;
    this.onFrame(this.snapshot());
  }

  publish(force = false, now = performance.now()) {
    if (!force && now - this.lastPublishAt < HUD_INTERVAL_MS) return;
    this.lastPublishAt = now;
    this.onPublish(this.snapshot());
  }

  destroy() {
    this.stopLoop();
  }
}

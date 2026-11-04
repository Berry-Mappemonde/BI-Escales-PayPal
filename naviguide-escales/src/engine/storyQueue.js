/**
 * E5 story file. Fire-and-forget.
 * Cascade NIM → OpenRouter (± :online) → Claude
 * on the event JSON already collected.
 * Not Nemotron. Not Token Factory. Not Tavily world-search.
 * Play never awaits this.
 */

const API_URL = import.meta.env?.VITE_API_URL ?? "";
const FETCH_MS = 25000;
export const MAX_STORY_PENDING = 3;
export const KEEP_STORY_TYPES = Object.freeze([
  "marina-refuge",
  "cyclone-nearby",
  "depth-alert",
  "wind-gale",
]);

const jobs = new Map();
const listeners = new Set();

export function resetStoryQueue() {
  for (const job of jobs.values()) job._ctrl?.abort();
  jobs.clear();
}

export function pendingStoryCount() {
  return pendingList().length;
}

export function subscribeStories(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify(job) {
  for (const fn of listeners) {
    try { fn(job); } catch { /* ignore subscriber errors */ }
  }
}

export function shouldEnqueueStory(ev, { written = false } = {}) {
  // Never by itself — only the Brut/Rédigé switch (written) buys Super.
  if (!written) return false;
  if (!ev || ev.judge === "hide") return false;
  const st = ev.story?.status;
  if (st === "pending" || st === "ready") return false;
  return ev.judge === "now";
}

/**
 * The orders that made THIS event switch (frozen at detection), not the 40 constants.
 * One `value` per id. The model cites them; it never invents another number.
 */
function skipperBlock(ev) {
  const s = ev?.skipper;
  if (!s || !Array.isArray(s.used)) return null;
  const seen = new Set();
  const used = [];
  for (const u of s.used) {
    if (!u?.id || seen.has(u.id) || !Number.isFinite(u.value)) continue;
    seen.add(u.id);
    used.push({ id: u.id, value: u.value, unit: u.unit ?? "", source: u.source ?? "usage", rule: u.rule ?? null });
  }
  return {
    profile: s.profile,
    profile_phrase: s.profile_phrase ?? null,
    comfort: s.comfort ?? "normal",
    boat: s.boat ? { name: s.boat.name ?? null, loaM: s.boat.loaM ?? null, draftM: s.boat.draftM ?? null } : null,
    used,
  };
}

export function storyPayload(ev, lang = "fr") {
  const p = ev?.payload || {};
  const pageUrl = p.amp?.visit_url || p.poe?.url || p.harbour?.url || null;
  const gold = Boolean(p.zee?.gold_pack);
  const needPage = Boolean(
    pageUrl
    && (gold || ev.severity === "alert" || ev.judgeReason === "skipper-click"),
  );
  return {
    event: ev.type,
    eventId: ev.id,
    stableKey: ev.stableKey,
    type: ev.type,
    lang,
    kind: ev.kind || p.kind || null,
    whenNm: ev.whenNm,
    filmCum: ev.filmCum,
    name: ev.name || null,
    severity: ev.severity,
    judge: ev.judge,
    judgeReason: ev.judgeReason || null,
    phrase: ev.phrase || null,
    payload: p,
    skipper: skipperBlock(ev),
    pageUrl: needPage ? pageUrl : null,
    needPage,
    tavily: null,
    nvidia: null,
  };
}

function pendingList() {
  return [...jobs.values()].filter((j) => j.status === "pending");
}

function evictOldestLater() {
  const droppable = pendingList()
    .filter((j) => !KEEP_STORY_TYPES.includes(j.type))
    .sort((a, b) => (a.enqueuedAt || 0) - (b.enqueuedAt || 0));
  const victim = droppable[0];
  if (!victim) return false;
  victim.status = "failed";
  victim.reason = "evicted";
  victim.tavily = null;
  victim.nvidia = null;
  victim._ctrl?.abort();
  notify({ ...victim });
  jobs.delete(victim.eventId);
  return true;
}

async function runStory(body, job) {
  const ctrl = new AbortController();
  job._ctrl = ctrl;
  const kill = setTimeout(() => ctrl.abort(), FETCH_MS);
  try {
    const r = await fetch(`${API_URL}/ici/story`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    const data = r.ok ? await r.json() : null;
    if (data?.status === "ready" && data.text) {
      job.status = "ready";
      job.text = data.text;
      job.engine = data.engine || null;
      job.source = data.source || data.engine || null;
      job.model = data.model || null;
      job.tier = data.tier || null;
      job.ai_model = data.ai_model || data.model || null;
      job.nvidia = data.nvidia ?? data.engine ?? null;
      job.tavily = null;
    } else {
      job.status = "failed";
      job.reason = data?.reason || `http_${r.status}`;
      job.tavily = null;
      job.nvidia = null;
    }
  } catch (err) {
    job.status = "failed";
    job.reason = err?.name === "AbortError" ? "timeout" : "network";
    job.tavily = null;
    job.nvidia = null;
  } finally {
    clearTimeout(kill);
    notify({ ...job });
  }
}

export function enqueueStory(eventJson) {
  const id = eventJson?.eventId || eventJson?.id;
  if (!id) {
    return { status: "failed", reason: "no-id", tavily: null, nvidia: null, cascade: "nim-or-claude" };
  }
  const existing = jobs.get(id);
  if (existing && (existing.status === "pending" || existing.status === "ready")) {
    return existing;
  }

  const type = eventJson.event || eventJson.type;
  const keep = KEEP_STORY_TYPES.includes(type);
  if (pendingList().length >= MAX_STORY_PENDING) {
    if (!keep && !evictOldestLater()) {
      return {
        status: "template",
        tavily: null,
        nvidia: null,
        cascade: "nim-or-claude",
        reason: "queue-full",
      };
    }
    if (keep && pendingList().length >= MAX_STORY_PENDING) {
      evictOldestLater();
    }
  }

  const job = {
    eventId: id,
    stableKey: eventJson.stableKey || null,
    type,
    status: "pending",
    tavily: null,
    nvidia: null,
    cascade: "nim-or-claude",
    text: null,
    enqueuedAt: Date.now(),
  };
  jobs.set(id, job);
  notify(job);
  void runStory(eventJson, job);
  return job;
}

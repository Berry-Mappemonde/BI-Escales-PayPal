/**
 * Lecture à voix haute — `speechSynthesis` du navigateur : gratuit, local,
 * zéro LLM (décision du 18 sept. 2026 : l'histoire est *lue*, pas dictée).
 * Voix prêtes, phrases courtes, keep-alive Chrome, repli linéaire.
 */

export const VOICES_WAIT_MS = 1000;
export const VOICE_IMMEDIATE_END_MS = 500;
export const UTTERANCE_KEEPALIVE_MS = 10_000;
export const SENTENCE_MAX_CHARS = 200;
/** Après speak() : ni onstart ni onboundary → on lâche la voix. */
export const VOICE_LEAD_MS = 2500;
/** Horloge de repli et toise d'énoncé : ~60 ms / caractère. */
export const VOICE_MS_PER_CHAR = 60;
/** Marge pour ne pas couper une phrase longue dont les mots tombent encore. */
export const SENTENCE_TIME_SLACK = 4;

export const VOICE_PREFS = {
  en: [
    "Google UK English Female",
    "Google US English",
    "Samantha",
    "Daniel",
    "Karen",
    "Moira",
  ],
  fr: [
    "Google français",
    "Thomas",
    "Amélie",
    "Audrey",
  ],
};

let keepAliveTimer = null;
/** Timers d'énoncé (lead + limite) : un `cancel()` ne doit pas les laisser tirer. */
let speakTimers = [];
/** Incrémenté à chaque `stopSpeaking` : un `onend` de `cancel()` ne relance rien. */
let speakGeneration = 0;

/**
 * Limite d'un énoncé : assez large pour une phrase de 200 car. lue vraiment
 * (~13 s à 15 car./s), assez courte pour un `onend` qui ne vient jamais.
 */
export function sentenceTimeLimitMs(text, {
  leadMs = VOICE_LEAD_MS,
  msPerChar = VOICE_MS_PER_CHAR,
  slack = SENTENCE_TIME_SLACK,
} = {}) {
  const n = Math.max(1, String(text || "").length);
  const lead = Number.isFinite(Number(leadMs)) ? Math.max(0, Number(leadMs)) : VOICE_LEAD_MS;
  const ms = Number.isFinite(Number(msPerChar)) && Number(msPerChar) > 0
    ? Number(msPerChar)
    : VOICE_MS_PER_CHAR;
  const factor = Number.isFinite(Number(slack)) && Number(slack) > 0
    ? Number(slack)
    : SENTENCE_TIME_SLACK;
  return lead + n * ms * factor;
}

/** Briefing text as spoken: no URLs, no arrows/glyphs, tidy spaces. */
export function spokenText(text) {
  return String(text || "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[↗◎•·|]/g, " ")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\.\s*\./g, ".")
    .trim();
}

export function canSpeak(win = typeof window !== "undefined" ? window : null) {
  return Boolean(win?.speechSynthesis && typeof win.SpeechSynthesisUtterance === "function");
}

/** Synthèse présente, pas un bot — les voix peuvent encore charger. */
export function voiceMayLead(win = typeof window !== "undefined" ? window : null) {
  if (!canSpeak(win)) return false;
  if (win.navigator?.webdriver) return false;
  return true;
}

/** Voix réellement disponible (Playwright / headless : on reste en mode linéaire). */
export function canLeadWithVoice(win = typeof window !== "undefined" ? window : null) {
  if (!voiceMayLead(win)) return false;
  try {
    return (win.speechSynthesis.getVoices() || []).length > 0;
  } catch {
    return false;
  }
}

export function isSpeaking(win = typeof window !== "undefined" ? window : null) {
  return Boolean(win?.speechSynthesis?.speaking);
}

function clearKeepAlive() {
  if (keepAliveTimer == null) return;
  const clearFn = typeof clearInterval === "function" ? clearInterval : null;
  try { clearFn?.(keepAliveTimer); } catch { /* ignore */ }
  keepAliveTimer = null;
}

function clearSpeakTimers(win) {
  const clearFn = win?.clearTimeout?.bind(win)
    || (typeof clearTimeout === "function" ? clearTimeout : null);
  for (const id of speakTimers) {
    try { clearFn?.(id); } catch { /* ignore */ }
  }
  speakTimers = [];
}

function scheduleSpeakTimer(win, fn, ms) {
  const start = win?.setTimeout?.bind(win)
    || (typeof setTimeout === "function" ? setTimeout : null);
  if (!start) return null;
  const id = start(fn, Math.max(0, Number(ms) || 0));
  if (id && typeof id.unref === "function") id.unref();
  speakTimers.push(id);
  return id;
}

export function stopSpeaking(win = typeof window !== "undefined" ? window : null) {
  speakGeneration += 1;
  clearKeepAlive();
  clearSpeakTimers(win);
  try {
    win?.speechSynthesis?.cancel();
  } catch {
    /* no synthesis available */
  }
}

export function getVoices(win = typeof window !== "undefined" ? window : null) {
  try {
    return win?.speechSynthesis?.getVoices?.() || [];
  } catch {
    return [];
  }
}

/** Attend `voiceschanged` au plus `timeoutMs` (Chrome : liste vide au premier appel). */
export function waitForVoices(win = typeof window !== "undefined" ? window : null, timeoutMs = VOICES_WAIT_MS) {
  const existing = getVoices(win);
  if (existing.length) return Promise.resolve(existing);
  const synth = win?.speechSynthesis;
  if (!synth) return Promise.resolve([]);
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      try { synth.removeEventListener?.("voiceschanged", onChange); } catch { /* ignore */ }
      if (synth.onvoiceschanged === onChange) synth.onvoiceschanged = null;
      resolve(getVoices(win));
    };
    const onChange = () => finish();
    try { synth.addEventListener?.("voiceschanged", onChange); } catch { /* ignore */ }
    try { synth.onvoiceschanged = onChange; } catch { /* ignore */ }
    const wait = Number.isFinite(Number(timeoutMs)) ? Math.max(0, Number(timeoutMs)) : VOICES_WAIT_MS;
    const start = typeof setTimeout === "function" ? setTimeout : null;
    if (start) {
      const t = start(finish, wait);
      if (t && typeof t.unref === "function") t.unref();
    } else {
      finish();
    }
  });
}

export function pickVoice(voices, lang = "fr") {
  const list = Array.isArray(voices) ? voices : [];
  const key = lang === "en" ? "en" : "fr";
  const prefs = VOICE_PREFS[key];
  for (const name of prefs) {
    const hit = list.find((v) => String(v?.name || "") === name);
    if (hit) return hit;
  }
  const prefix = key;
  return list.find((v) => String(v?.lang || "").toLowerCase().startsWith(prefix)) || null;
}

export function utteranceRate(lang, rate) {
  const n = Number(rate);
  if (Number.isFinite(n) && n !== 1) {
    return Math.max(0.9, Math.min(1.25, n));
  }
  return lang === "en" ? 0.95 : 1;
}

/**
 * Découpe un chapitre en phrases ≤ `max` caractères, avec l'index de départ
 * dans le texte d'origine (charIdx global monotone).
 */
export function splitUtterances(text, max = SENTENCE_MAX_CHARS) {
  const src = String(text || "");
  if (!src) return [];
  const limit = Number.isFinite(Number(max)) && Number(max) > 0 ? Number(max) : SENTENCE_MAX_CHARS;
  const rawParts = src.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [src];
  const pieces = [];
  for (const raw of rawParts) {
    const sentence = raw.replace(/^\s+/, "");
    if (!sentence) continue;
    if (sentence.length <= limit) {
      pieces.push(sentence);
      continue;
    }
    let buf = "";
    for (const word of sentence.split(/\s+/)) {
      if (!word) continue;
      const next = buf ? `${buf} ${word}` : word;
      if (next.length <= limit) {
        buf = next;
        continue;
      }
      if (buf) pieces.push(buf);
      if (word.length <= limit) {
        buf = word;
      } else {
        for (let i = 0; i < word.length; i += limit) {
          const slice = word.slice(i, i + limit);
          if (slice.length === limit) pieces.push(slice);
          else buf = slice;
        }
      }
    }
    if (buf) pieces.push(buf);
  }
  let from = 0;
  return pieces.map((piece) => {
    const start = src.indexOf(piece, from);
    const at = start < 0 ? from : start;
    from = at + piece.length;
    return { text: piece, start: at };
  });
}

/**
 * onend sans boundary en < 500 ms :
 * — des chunks restent → avancer (reprendre au suivant, jamais finir) ;
 * — dernier chunk → une relance, puis mode linéaire.
 */
export function voiceEndKind({
  hadBoundary,
  elapsedMs,
  alreadyRetried,
  hasMoreChunks = false,
} = {}) {
  const elapsed = Number(elapsedMs);
  if (!hadBoundary && Number.isFinite(elapsed) && elapsed < VOICE_IMMEDIATE_END_MS) {
    if (hasMoreChunks) return "advance";
    return alreadyRetried ? "linear" : "retry";
  }
  return "advance";
}

function nowMs(win) {
  const perf = win?.performance || (typeof performance !== "undefined" ? performance : null);
  if (perf && typeof perf.now === "function") return perf.now();
  return Date.now();
}

function armKeepAlive(win) {
  clearKeepAlive();
  const start = win?.setInterval?.bind(win) || (typeof setInterval === "function" ? setInterval : null);
  if (!start) return;
  keepAliveTimer = start(() => {
    try {
      const synth = win?.speechSynthesis;
      if (!synth?.speaking) return;
      // `pause()`+`resume()` coupe l'utterance (onend) : on ne fait que `resume()`.
      synth.resume();
    } catch { /* Chrome keep-alive */ }
  }, UTTERANCE_KEEPALIVE_MS);
  if (keepAliveTimer && typeof keepAliveTimer.unref === "function") keepAliveTimer.unref();
}

function abandonUtterance(opts, win) {
  clearKeepAlive();
  clearSpeakTimers(win);
  try { win?.speechSynthesis?.cancel(); } catch { /* ignore */ }
  if (opts.onLeadFailed) opts.onLeadFailed();
  else opts.onEnd?.();
}

function beginUtterances(body, lang, opts, voices) {
  const win = opts.win;
  const generation = speakGeneration;
  const stillThisSpeak = () => generation === speakGeneration;
  const chunks = splitUtterances(body, SENTENCE_MAX_CHARS);
  if (!chunks.length) {
    if (stillThisSpeak()) opts.onEnd?.();
    return;
  }
  const voice = pickVoice(voices, lang);
  const rate = utteranceRate(lang, opts.rate);
  const utterLang = lang === "en" ? "en-GB" : "fr-FR";
  let chunkIdx = 0;
  let retried = false;
  const leadMs = Number.isFinite(Number(opts.leadMs)) ? Number(opts.leadMs) : VOICE_LEAD_MS;

  const speakChunk = () => {
    if (!stillThisSpeak()) return;
    if (chunkIdx >= chunks.length) {
      clearKeepAlive();
      clearSpeakTimers(win);
      if (stillThisSpeak()) opts.onEnd?.();
      return;
    }
    const chunk = chunks[chunkIdx];
    const utter = new win.SpeechSynthesisUtterance(chunk.text);
    utter.lang = utterLang;
    utter.rate = rate;
    if (voice) utter.voice = voice;
    let hadBoundary = false;
    let heardStart = false;
    let settled = false;
    const started = nowMs(win);
    const limitMs = Number.isFinite(Number(opts.sentenceLimitMs))
      ? Number(opts.sentenceLimitMs)
      : sentenceTimeLimitMs(chunk.text, { leadMs });
    utter.onstart = () => {
      heardStart = true;
    };
    utter.onboundary = (ev) => {
      heardStart = true;
      hadBoundary = true;
      const idx = Number(ev?.charIndex);
      if (Number.isFinite(idx)) opts.onBoundary?.(chunk.start + idx);
    };
    const finishUtter = () => {
      if (!stillThisSpeak() || settled) return;
      settled = true;
      clearSpeakTimers(win);
      const hasMoreChunks = chunkIdx < chunks.length - 1;
      const kind = voiceEndKind({
        hadBoundary,
        elapsedMs: nowMs(win) - started,
        alreadyRetried: retried,
        hasMoreChunks,
      });
      if (kind === "retry") {
        retried = true;
        speakChunk();
        return;
      }
      if (kind === "linear") {
        clearKeepAlive();
        if (opts.onLeadFailed) opts.onLeadFailed();
        else opts.onEnd?.();
        return;
      }
      retried = false;
      chunkIdx += 1;
      speakChunk();
    };
    utter.onend = finishUtter;
    utter.onerror = finishUtter;
    clearSpeakTimers(win);
    scheduleSpeakTimer(win, () => {
      if (!stillThisSpeak() || settled || heardStart) return;
      settled = true;
      speakGeneration += 1;
      abandonUtterance(opts, win);
    }, leadMs);
    scheduleSpeakTimer(win, () => {
      if (!stillThisSpeak() || settled) return;
      settled = true;
      speakGeneration += 1;
      abandonUtterance(opts, win);
    }, limitMs);
    armKeepAlive(win);
    win.speechSynthesis.speak(utter);
  };
  speakChunk();
}

/**
 * Reads `text` aloud in `lang` ("fr" | "en"). Returns false when the browser
 * cannot speak. `onEnd` fires when the reading finishes or is cancelled.
 * `onLeadFailed` : onend immédiat après une relance → le film passe en linéaire
 * sans se terminer. Sans ce callback (Écouter), onEnd libère le bouton.
 */
export function speak(text, lang = "fr", {
  onEnd,
  onBoundary,
  onLeadFailed,
  rate = 1,
  leadMs = VOICE_LEAD_MS,
  sentenceLimitMs,
  win = typeof window !== "undefined" ? window : null,
} = {}) {
  if (!canSpeak(win)) return false;
  const body = spokenText(text);
  if (!body) return false;
  stopSpeaking(win);
  const opts = { onEnd, onBoundary, onLeadFailed, rate, leadMs, sentenceLimitMs, win };
  const generation = speakGeneration;
  const voices = getVoices(win);
  if (voices.length) {
    beginUtterances(body, lang, opts, voices);
    return true;
  }
  waitForVoices(win, VOICES_WAIT_MS).then((ready) => {
    if (generation !== speakGeneration) return;
    if (!ready.length) {
      if (opts.onLeadFailed) opts.onLeadFailed();
      else opts.onEnd?.();
      return;
    }
    beginUtterances(body, lang, opts, ready);
  });
  return true;
}

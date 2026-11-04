/**
 * Toponymes — même table que le serveur (`toponymsTable.json`).
 * Pays et eaux : exonyme de la langue du récit. Ports / AMP : nom d'origine.
 */
import table from "./toponymsTable.json" with { type: "json" };

const PREP_HEAD = /^(de |du |des |d['’])/i;
const PAREN_RE = /\(([^)]+)\)/;
const DISTINGUISHER_RE = /\s*\((?:partie française|partie néerlandaise|french side|dutch side)\)\s*/i;
const SMALL = new Set(["de", "da", "do", "del", "della", "of", "the", "and", "la", "le", "du", "des", "y", "e", "di"]);
const ACCENT = {
  coruna: "Coruña",
  coruña: "Coruña",
  muxia: "Muxía",
  muxía: "Muxía",
  camarinas: "Camariñas",
  camariñas: "Camariñas",
  almeria: "Almería",
  almería: "Almería",
  mahon: "Mahón",
  mahón: "Mahón",
};

const rows = table.territories || [];
const aliasRx = rows.flatMap((row) => (row.aliases || []).map((a) => [new RegExp(a, "i"), row]));
const byMrgid = new Map();
const byTerritory = new Map();
for (const row of rows) {
  if (Number.isInteger(row.mrgid) && !byMrgid.has(row.mrgid)) byMrgid.set(row.mrgid, row);
  if (row.territory) byTerritory.set(row.territory, row);
}
for (const [mid, id] of [[48966, "fr"], [48976, "fr"], [48948, "nc"]]) {
  const row = rows.find((r) => r.id === id);
  if (row && !byMrgid.has(mid)) byMrgid.set(mid, row);
}

function isEn(lang) {
  return String(lang || "").toLowerCase().startsWith("en");
}

function matchAliases(text) {
  const blob = String(text || "").trim();
  if (!blob) return null;
  for (const [rx, row] of aliasRx) {
    if (rx.test(blob)) return row;
  }
  return null;
}

export function lookup(raw, { mrgid = null, territory = null } = {}) {
  const key = String(territory || "").trim();
  if (key && key !== "france_metropolitaine" && byTerritory.has(key)) return byTerritory.get(key);
  if (Number.isInteger(mrgid) && byMrgid.has(mrgid)) return byMrgid.get(mrgid);
  if (key && byTerritory.has(key)) return byTerritory.get(key);
  const blob = String(raw || "").trim();
  if (!blob) return null;
  const inner = PAREN_RE.exec(blob);
  if (inner) {
    const hit = matchAliases(inner[1].trim());
    if (hit) return hit;
  }
  return matchAliases(blob);
}

function isOverseas(row) {
  const terr = String(row.territory || "").trim();
  return Boolean(terr) && terr !== "france_metropolitaine";
}

function watersTail(row, lang) {
  if (isEn(lang)) {
    const extra = String(row.en || "").trim();
    const adj = String(row.adj_en || "").trim();
    if (extra && (row.shared || isOverseas(row))) return extra;
    if (adj) return adj;
    return extra;
  }
  const prep = String(row.prep_fr || "").trim();
  const adj = String(row.adj_fr || "").trim();
  if (prep && (row.shared || isOverseas(row) || !adj)) return prep;
  if (adj) return adj;
  return prep || String(row.fr || "").trim();
}

export function watersLabel(name, lang = "fr", opts = {}) {
  const row = lookup(name, opts);
  if (row?.kind === "high_seas") return isEn(lang) ? "the high seas" : "haute mer";
  if (row?.kind === "overlap") {
    return isEn(lang)
      ? "disputed waters of Western Sahara"
      : "les eaux disputées du Sahara occidental";
  }
  if (!row) return "";
  const tail = watersTail(row, lang);
  if (!tail) return "";
  if (isEn(lang)) return /water/i.test(tail) ? tail : `${tail} waters`;
  if (tail.startsWith("disput")) return `les eaux ${tail}`;
  return `les eaux ${tail}`;
}

export function sheetLabel(name, lang = "fr", opts = {}) {
  const row = lookup(name, opts);
  if (!row) return "";
  if (row.kind === "high_seas") return isEn(lang) ? "High seas" : "Haute mer";
  if (row.kind === "overlap") {
    return isEn(lang)
      ? "Disputed waters of Western Sahara"
      : "Eaux disputées du Sahara occidental";
  }
  if (isEn(lang)) {
    const adjEn = String(row.adj_en || "").trim();
    const extra = String(row.en || "").trim();
    const terr = String(row.territory || "");
    if (adjEn) {
      if (terr === "france_metropolitaine") return `${adjEn} EEZ (metropolitan France)`;
      if (terr && extra && !adjEn.toLowerCase().includes(extra.toLowerCase())) {
        return `${adjEn} EEZ (${extra})`;
      }
      return `${adjEn} EEZ`;
    }
    return extra ? `${extra} EEZ` : "EEZ";
  }
  const adjEez = String(row.adj_eez_fr || "").trim();
  const prep = String(row.prep_fr || "").trim();
  if (adjEez) {
    let label = `Zone économique exclusive ${adjEez}`;
    const extra = String(row.fr || "").trim();
    const terr = String(row.territory || "");
    if (terr && terr !== "france_metropolitaine" && extra && !label.toLowerCase().includes(extra.toLowerCase())) {
      label = `${label} (${extra})`;
    } else if (terr === "france_metropolitaine") {
      label = `${label} (France métropolitaine)`;
    }
    return label;
  }
  if (prep) return `Zone économique exclusive ${prep}`;
  const adj = String(row.adj_fr || "").trim();
  if (adj) return `Zone économique exclusive ${adj.replace(/s$/, "")}`;
  return `Zone économique exclusive (${row.fr})`;
}

export function spokenZeeName(zee, lang = "fr") {
  if (!zee) return "";
  const names = zee.names;
  if (names && typeof names === "object") {
    const picked = names[isEn(lang) ? "en" : "fr"];
    if (picked) return picked;
  }
  const opts = { mrgid: Number.isInteger(zee.mrgid) ? zee.mrgid : null, territory: zee.territory || null };
  return sheetLabel(zee.name, lang, opts);
}

export function originName(raw) {
  const s = String(raw || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  const letters = s.replace(/[^A-Za-zÀ-ÿ]/g, "");
  if (letters.length < 3) return s;
  const up = [...letters].filter((c) => c === c.toUpperCase() && c !== c.toLowerCase()).length;
  if (up / letters.length < 0.85) return s;
  return s.split(" ").map((word, index) => {
    const folded = word.toLowerCase();
    if (ACCENT[folded]) return ACCENT[folded];
    return folded.split("-").map((bit, j) => {
      if (!bit) return bit;
      if (ACCENT[bit]) return ACCENT[bit];
      if ((index > 0 || j > 0) && SMALL.has(bit)) return bit;
      return bit.slice(0, 1).toUpperCase() + bit.slice(1);
    }).join("-");
  }).join(" ");
}

export function consecutiveHomonyms(text) {
  const blob = String(text || "");
  const chunkRe = /(?:les eaux|celles|waters)\s+(?:de |d['’]|du |des )?([^,;.]+?)(?=, (?:puis|then)\b|\.|$)/gi;
  const hits = [];
  let prevCore = "";
  let prevRaw = "";
  let prevDist = false;
  let m = chunkRe.exec(blob);
  while (m) {
    const raw = m[0];
    const distinguished = DISTINGUISHER_RE.test(raw);
    const core = raw.replace(DISTINGUISHER_RE, " ").toLowerCase()
      .replace(/\b(les eaux|celles|waters|de|du|des|d['’]|the)\b/g, " ")
      .replace(/\bsint\b/g, "saint")
      .replace(/\bmaarten\b/g, "martin")
      .replace(/[^a-zà-ÿ]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (prevCore && core && core === prevCore && !(distinguished && prevDist)) {
      hits.push(`${prevRaw} → ${raw}`);
    }
    prevCore = core;
    prevRaw = raw;
    prevDist = distinguished;
    m = chunkRe.exec(blob);
  }
  return hits;
}

export { PREP_HEAD };
export const TOPONYM_SOURCES = table.sources || [];

/**
 * Écart n° 43 : provenance Tavily du film rédigé (Revoir → Rédigé).
 * Le serveur range au clic Rédigé le résultat d'une recherche Tavily sur le
 * dernier port du film (`webContext`). On n'affiche que ce qui est servi :
 * port, titres, domaines et liens — jamais un extrait, jamais une source inventée.
 */
const MAX_SOURCES = 3;

function domainOf(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
  }
}

/** Clé de dédoublonnage : schéma et hôte en minuscules, sans www., sans fragment ni « / » final. */
export function normalizeSourceUrl(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    const path = u.pathname.replace(/\/+$/, "");
    return `${u.protocol.toLowerCase()}//${host}${u.port ? `:${u.port}` : ""}${path}${u.search}`;
  } catch {
    return String(url || "").trim();
  }
}

/** Clé de dédoublonnage (schéma/hôte minuscules, sans www., sans / final). */
export function normalizeFilmWebSourceUrl(url) {
  try {
    const u = new URL(url);
    let host = u.hostname.toLowerCase();
    if (host.startsWith("www.")) host = host.slice(4);
    if (!host) return "";
    let path = u.pathname;
    if (path.length > 1 && path.endsWith("/")) path = path.slice(0, -1);
    return `${u.protocol.toLowerCase()}//${host}${u.port ? `:${u.port}` : ""}${path}${u.search}`;
  } catch {
    return "";
  }
}

export function publicFilmWebContext(data) {
  const ctx = data?.webContext;
  if (!ctx || typeof ctx !== "object" || ctx.basis !== "tavily") return null;
  const port = String(ctx.port || "").trim();
  const sources = [];
  const seen = new Set();
  for (const row of Array.isArray(ctx.sources) ? ctx.sources : []) {
    const url = String(row?.url || "").trim();
    if (!/^https?:\/\//i.test(url)) continue;
    const key = normalizeFilmWebSourceUrl(url);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const domain = String(row?.domain || "").trim() || domainOf(url);
    if (!domain) continue;
    sources.push({ url, domain, title: String(row?.title || "").trim() || domain });
    if (sources.length >= MAX_SOURCES) break;
  }
  if (!port || !sources.length) return null;
  return { port, fetchedAt: ctx.fetchedAt || null, sources };
}

/**
 * Contexte web à garder quand un nouveau film est servi : toujours celui du
 * film servi, jamais celui du précédent (film B sans Tavily → null).
 */
export function nextFilmWebContext(_previous, resolved) {
  return resolved?.webContext || null;
}

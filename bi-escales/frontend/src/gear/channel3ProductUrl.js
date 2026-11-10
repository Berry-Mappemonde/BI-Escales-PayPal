/** @param {unknown} url */
export function isAbsoluteHttpsUrl(url) {
  const token = String(url || "").trim();
  if (!token) return false;
  try {
    const parsed = new URL(token);
    return parsed.protocol === "https:" && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

/** @param {unknown} url */
export function isChannel3HomepageUrl(url) {
  const token = String(url || "").trim();
  if (!token || !isAbsoluteHttpsUrl(token)) return false;
  return /^https:\/\/(?:www\.)?trychannel3\.com\/?$/i.test(token);
}

/** @param {unknown} url */
export function normalizeChannel3ProductUrl(url) {
  const token = String(url || "").trim();
  if (!token || !isAbsoluteHttpsUrl(token) || isChannel3HomepageUrl(token)) return "";
  try {
    const host = new URL(token).hostname.toLowerCase();
    if (host === "trychannel3.com" || host === "www.trychannel3.com") return "";
  } catch {
    return "";
  }
  return token;
}

/** @param {Record<string, unknown> | null | undefined} props */
export function gearPageHref(props) {
  if (String(props?.project_kind || "") !== "gear_project") return "";
  if (!props?.fully_funded) return "";
  return normalizeChannel3ProductUrl(props?.channel3_buy_url || props?.url);
}

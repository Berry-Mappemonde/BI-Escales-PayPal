/** Montant saisi pour une promesse projet (formats EUR courants). */

/** @typedef {"empty" | "invalid" | "below_min" | "ok"} ProjectAmountKind */

/**
 * @param {string} raw
 * @returns {{ kind: ProjectAmountKind, apiAmount?: string }}
 */
export function parseProjectPledgeAmount(raw) {
  const text = String(raw ?? "").trim().replace(/\s/g, "");
  if (!text) return { kind: "empty" };

  let api = "";

  if (text.includes(",") && text.includes(".")) {
    return { kind: "invalid" };
  } else if (text.includes(",")) {
    const parts = text.split(",");
    if (parts.length !== 2) return { kind: "invalid" };
    const [whole, frac] = parts;
    if (!/^\d+$/.test(whole) || !/^\d+$/.test(frac)) return { kind: "invalid" };
    if (frac.length === 0 || frac.length > 2) return { kind: "invalid" };
    api = `${whole}.${frac.padEnd(2, "0")}`;
  } else if (text.includes(".")) {
    const parts = text.split(".");
    if (parts.length !== 2) return { kind: "invalid" };
    const [whole, frac] = parts;
    if (!/^\d+$/.test(whole) || !/^\d+$/.test(frac)) return { kind: "invalid" };
    if (frac.length === 0 || frac.length > 2) return { kind: "invalid" };
    api = `${whole}.${frac.padEnd(2, "0")}`;
  } else if (/^\d+$/.test(text)) {
    api = `${text}.00`;
  } else {
    return { kind: "invalid" };
  }

  const numeric = Number(api);
  if (!Number.isFinite(numeric) || numeric <= 0) return { kind: "empty" };
  if (numeric < 1) return { kind: "below_min", apiAmount: api };
  return { kind: "ok", apiAmount: api };
}

/** @deprecated use parseProjectPledgeAmount */
export function normalizeEuroAmountForApi(raw) {
  const parsed = parseProjectPledgeAmount(raw);
  return parsed.apiAmount || "";
}

/** @deprecated use parseProjectPledgeAmount */
export function euroAmountNumeric(raw) {
  const parsed = parseProjectPledgeAmount(raw);
  if (parsed.kind === "ok" || parsed.kind === "below_min") {
    return Number(parsed.apiAmount);
  }
  return Number.NaN;
}

/** @deprecated use parseProjectPledgeAmount */
export function isBelowProjectPledgeMinimum(raw) {
  const parsed = parseProjectPledgeAmount(raw);
  return parsed.kind === "empty" || parsed.kind === "below_min" || parsed.kind === "invalid";
}

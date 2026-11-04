/**
 * ProtectedSeas Entry / Speed → pleasure-craft traffic.
 * 0 allowed, 1 prohibited, 2 restricted, 3 unknown.
 */

export function asActivity(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0 || n > 3) return null;
  return n;
}

export function trafficKind(entry, speed) {
  const e = asActivity(entry);
  const s = asActivity(speed);
  if (e === 1 || s === 1) return "forbidden";
  if (e === 2 || s === 2) return "regulated";
  if (e === 0 && (s == null || s === 0 || s === 3)) return "allowed";
  if (e == null && s === 0) return "allowed";
  return "unknown";
}

export function summarizeAmpTraffic(amps, lang = "fr") {
  const list = (amps || []).filter((a) => a && (a.name || a.site_id));
  const kindOf = (a) => a.traffic || trafficKind(a.entry, a.speed);
  const crossingForb = list.filter((a) => a.inside && kindOf(a) === "forbidden");
  const crossingReg = list.filter((a) => a.inside && kindOf(a) === "regulated");
  const nearReg = list.filter((a) => !a.inside && kindOf(a) === "regulated");
  const en = lang === "en";
  const name = (a) => a.name || a.site_id || (en ? "MPA" : "AMP");
  if (crossingForb[0]) {
    return {
      kind: "forbidden-inside",
      name: name(crossingForb[0]),
      line: en
        ? `No transit: ${name(crossingForb[0])}`
        : `Circulation interdite : ${name(crossingForb[0])}`,
    };
  }
  if (crossingReg[0]) {
    return {
      kind: "regulated-inside",
      name: name(crossingReg[0]),
      line: en
        ? `Regulated transit: ${name(crossingReg[0])}`
        : `Circulation régulée : ${name(crossingReg[0])}`,
    };
  }
  if (nearReg[0]) {
    const nm = Number.isFinite(nearReg[0].nm) ? nearReg[0].nm : null;
    const dist = nm != null ? (en ? ` (${nm} nm)` : ` (${String(nm).replace(".", ",")} nm)`) : "";
    return {
      kind: "regulated-near",
      name: name(nearReg[0]),
      line: en
        ? `Regulated transit nearby${dist}: ${name(nearReg[0])}`
        : `Circulation régulée à proximité${dist} : ${name(nearReg[0])}`,
    };
  }
  return { kind: null, name: null, line: "" };
}

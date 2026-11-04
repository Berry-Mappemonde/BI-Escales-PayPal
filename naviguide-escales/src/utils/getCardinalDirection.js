const DIRECTIONS_FR = [
  "N", "NNE", "NE", "ENE",
  "E", "ESE", "SE", "SSE",
  "S", "SSO", "SO", "OSO",
  "O", "ONO", "NO", "NNO",
];

const DIRECTIONS_EN = [
  "N", "NNE", "NE", "ENE",
  "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW",
  "W", "WNW", "NW", "NNW",
];

function degreesOf(input) {
  if (typeof input === "number") return input;
  if (input && typeof input === "object") return Number(input.degrees);
  return Number.NaN;
}

/** Cap cardinal. Accepte un nombre (App) ou `{ degrees }` (ancien contrat). */
export function getCardinalDirection(input, lang = "fr") {
  const degrees = degreesOf(input);
  if (!Number.isFinite(degrees)) return "";
  const wrapped = ((degrees % 360) + 360) % 360;
  const index = Math.round(wrapped / 22.5) % 16;
  const table = String(lang || "").toLowerCase().startsWith("en") ? DIRECTIONS_EN : DIRECTIONS_FR;
  return table[index];
}

export function numberLocale(lang = "fr") {
  return String(lang || "").toLowerCase().startsWith("en") ? "en-US" : "fr-FR";
}

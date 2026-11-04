/** English exonyms for French geographic labels in dossiers / journal (EN UI). */
const PLACE_EN = Object.freeze({
  "nouvelle-calédonie": "New Caledonia",
  "nouvelle-caledonie": "New Caledonia",
  "wallis-et-futuna": "Wallis and Futuna",
  "polynésie française": "French Polynesia",
  "polynesie francaise": "French Polynesia",
  "la réunion": "Réunion",
  "la reunion": "Réunion",
  "la sardaigne": "Sardinia",
  corse: "Corsica",
  "haute mer": "high seas",
});

export function localizePlaceName(name, lang = "fr") {
  const text = String(name || "").trim();
  if (!text || lang !== "en") return text;
  let out = text;
  const low = text.toLowerCase();
  for (const [fr, enName] of Object.entries(PLACE_EN)) {
    if (low.includes(fr)) {
      out = out.replace(new RegExp(fr.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), enName);
    }
  }
  return out;
}

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Les specs déjà écrites regardent l'écran français. Le visiteur neuf, lui, ouvre en anglais. */
export default async function globalSetup() {
  const port = Number(process.env.PW_PORT || 5174);
  const origin = `http://127.0.0.1:${port}`;
  const file = path.join(here, ".auth", "fr.json");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({
    cookies: [],
    origins: [{
      origin,
      localStorage: [{ name: "naviguide_lang_v4", value: "fr" }],
    }],
  }));
}

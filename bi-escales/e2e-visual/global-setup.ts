import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)));

export default function globalSetup() {
  fs.rmSync(path.join(root, "diagnostics"), { recursive: true, force: true });
  fs.rmSync(path.join(root, "screenshots"), { recursive: true, force: true });
}

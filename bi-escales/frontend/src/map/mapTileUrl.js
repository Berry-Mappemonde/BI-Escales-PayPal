/** Tile base URL per theme (NAVIGUIDE layers/styles.js TILE_URLS). */
import { TILE_URLS } from "../../../../naviguide-escales/src/layers/styles.js";

export function mapTileUrlForTheme(theme) {
  return theme === "light" ? TILE_URLS.light : TILE_URLS.dark;
}

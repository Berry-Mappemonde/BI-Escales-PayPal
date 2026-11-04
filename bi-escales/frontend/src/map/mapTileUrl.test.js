import { describe, expect, it } from "vitest";
import { TILE_URLS } from "../../../../naviguide-escales/src/layers/styles.js";
import { mapTileUrlForTheme } from "./mapTileUrl.js";

describe("mapTileUrlForTheme", () => {
  it("returns NAVIGUIDE light and dark tile templates", () => {
    expect(mapTileUrlForTheme("light")).toBe(TILE_URLS.light);
    expect(mapTileUrlForTheme("dark")).toBe(TILE_URLS.dark);
  });
});

import { describe, expect, it } from "vitest";
import { filterProjectFeatures } from "./filterProjectFeatures.js";

describe("filterProjectFeatures", () => {
  const features = [
    {
      properties: {
        id: "a",
        title: "Plastics",
        funder: "Ocean Foundation",
        category_group: "Other",
        description: "reduce plastic",
        location: "",
      },
    },
    {
      properties: {
        id: "b",
        title: "Coral",
        funder: "WWF",
        category_group: "Restoration",
        description: "",
        location: "Pacific",
      },
    },
  ];

  it("filtre comme ProjectList.js BI (recherche + catégorie)", () => {
    expect(filterProjectFeatures(features, { searchQuery: "plastic" }).map((f) => f.properties.id)).toEqual(["a"]);
    expect(filterProjectFeatures(features, { categoryFilter: "Restoration" }).map((f) => f.properties.id)).toEqual(["b"]);
    expect(filterProjectFeatures(features, { funderFilter: "WWF" }).map((f) => f.properties.id)).toEqual(["b"]);
  });
});

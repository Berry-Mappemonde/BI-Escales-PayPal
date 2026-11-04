import { describe, expect, it } from "vitest";
import { nextStopover } from "./nextStopover.js";

describe("nextStopover", () => {
  const stops = [
    { name: "A", milestoneId: "dep-a", nm: 0 },
    { name: "B", milestoneId: "dep-b", nm: 100 },
    { name: "C", milestoneId: "dep-c", nm: 200 },
  ];

  it("choisit la première escale dont le nm dépasse la position", () => {
    expect(nextStopover(stops, 50)?.milestoneId).toBe("dep-b");
    expect(nextStopover(stops, 100)?.milestoneId).toBe("dep-b");
    expect(nextStopover(stops, 150)?.milestoneId).toBe("dep-c");
  });
});

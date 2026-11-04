import { describe, expect, it } from "vitest";
import { formatLogbookEntry, escaleArrivalIso, logbookEntriesForStop } from "./journalDisplay.js";

describe("journalDisplay", () => {
  const schedule = {
    export: {
      escales: [
        { milestone_id: "dep-dakar", name: "Dakar", arrival_iso: "2027-02-01T14:00:00+00:00" },
      ],
    },
    logbook: {
      "dep-dakar": [
        {
          t: "2027-01-30T14:00:00Z",
          pos: { lat: 10.1, lon: -20.2 },
          label_fr: "Position — en route vers Dakar",
          label_en: "Position — underway for Dakar",
          kind: "position",
        },
        {
          t: "2027-02-01T14:00:00Z",
          pos: { lat: 14.7, lon: -17.4 },
          label_fr: "Escale — arrivée Dakar",
          label_en: "Stopover — arrival at Dakar",
          kind: "stop",
        },
      ],
    },
  };

  it("formats FR and EN logbook lines", () => {
    const entry = schedule.logbook["dep-dakar"][0];
    expect(formatLogbookEntry(entry, "fr")).toContain("en route vers Dakar");
    expect(formatLogbookEntry(entry, "en")).toContain("underway for Dakar");
  });

  it("reads arrival_iso and logbook rows from schedule", () => {
    expect(escaleArrivalIso(schedule, "dep-dakar")).toContain("2027-02-01");
    expect(logbookEntriesForStop(schedule, "dep-dakar")).toHaveLength(2);
  });
});

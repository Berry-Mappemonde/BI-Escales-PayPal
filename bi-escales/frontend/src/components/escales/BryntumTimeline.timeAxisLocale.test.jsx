import { describe, expect, it, vi } from "vitest";
import { rebuildTimelineTimeAxisHeaders } from "./BryntumTimeline.jsx";

/**
 * Simulates Bryntum leaving the last partial day cell in French after FR → EN when only
 * refreshTimeAxis(true) runs (reported in-browser as …08 Nov, 15 Nov, 16 nov.).
 */
function createPartialStaleTimeAxisMock(localeName = "FrFr") {
  const state = { localeName };
  const headerCells =
    localeName === "FrFr"
      ? ["nov. 2026", "08 nov.", "15 nov.", "16 nov."]
      : ["Nov 2026", "08 Nov", "15 Nov", "16 Nov"];

  const timeAxisView = {
    rendered: true,
    refresh: vi.fn((rebuild) => {
      if (!rebuild) return;
      if (state.localeName === "En") {
        headerCells[0] = "Nov 2026";
        headerCells[1] = "08 Nov";
        headerCells[2] = "15 Nov";
        // Bug: last partial tick keeps French month abbreviation.
      }
    }),
  };

  return {
    state,
    headerCells,
    isPainted: true,
    isHorizontal: true,
    infiniteScroll: false,
    timeAxisSubGrid: { scrollable: { element: { getBoundingClientRect: () => ({ width: 640 }) } } },
    refreshTimeAxis: vi.fn((rebuild) => {
      timeAxisView.refresh(rebuild);
    }),
    timeAxisViewModel: {
      update: vi.fn(() => {
        if (state.localeName === "En") {
          headerCells[0] = "Nov 2026";
          headerCells[1] = "08 Nov";
          headerCells[2] = "15 Nov";
          headerCells[3] = "16 Nov";
        } else if (state.localeName === "FrFr") {
          headerCells[0] = "nov. 2026";
          headerCells[1] = "08 nov.";
          headerCells[2] = "15 nov.";
          headerCells[3] = "16 nov.";
        }
      }),
    },
    timeAxisColumn: {
      refreshHeader: vi.fn(() => {
        if (state.localeName === "En") {
          headerCells[0] = "Nov 2026";
          headerCells[1] = "08 Nov";
          headerCells[2] = "15 Nov";
          headerCells[3] = "16 Nov";
        } else {
          headerCells[0] = "nov. 2026";
          headerCells[1] = "08 nov.";
          headerCells[2] = "15 nov.";
          headerCells[3] = "16 nov.";
        }
      }),
    },
    currentOrientation: { doUpdateTimeView: vi.fn() },
    onLocaleChange: vi.fn(),
    viewPreset: { id: "weekAndMonth" },
    presets: {
      getById: vi.fn((id) => (id === "weekAndMonth" ? { id, options: {} } : null)),
    },
    startDate: new Date("2026-11-08"),
    endDate: new Date("2026-11-17"),
    set viewPreset(preset) {
      state.lastPreset = preset;
    },
  };
}

function frenchMonthAbbreviationPresent(cells) {
  return cells.some((label) => /\b\d{1,2}\s+nov\./i.test(label) && !/Nov/.test(label));
}

describe("rebuildTimelineTimeAxisHeaders", () => {
  it("documents that refreshTimeAxis alone leaves the last French day cell", () => {
    const widget = createPartialStaleTimeAxisMock("FrFr");
    widget.state.localeName = "En";
    widget.refreshTimeAxis(true);
    expect(frenchMonthAbbreviationPresent(widget.headerCells)).toBe(true);
    expect(widget.headerCells.at(-1)).toBe("16 nov.");
  });

  it("regenerates every header cell after EN then FR (no stale nov. label in English)", () => {
    const widget = createPartialStaleTimeAxisMock("FrFr");

    for (const localeName of ["En", "FrFr", "En"]) {
      widget.state.localeName = localeName;
      rebuildTimelineTimeAxisHeaders(widget);
      if (localeName === "En") {
        expect(frenchMonthAbbreviationPresent(widget.headerCells)).toBe(false);
        expect(widget.headerCells).toEqual(["Nov 2026", "08 Nov", "15 Nov", "16 Nov"]);
      } else {
        expect(widget.headerCells.at(-1)).toBe("16 nov.");
      }
    }

    expect(widget.timeAxisViewModel.update).toHaveBeenCalled();
    expect(widget.timeAxisColumn.refreshHeader).toHaveBeenCalled();
    expect(widget.refreshTimeAxis).not.toHaveBeenCalled();
  });
});

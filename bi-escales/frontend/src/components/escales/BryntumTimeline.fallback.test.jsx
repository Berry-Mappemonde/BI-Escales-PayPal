import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";

vi.mock("./BryntumTimeline.jsx", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    loadBryntumTimelineModules: () => {
      actual.resetBryntumTimelineModulesForTests();
      return Promise.reject(new Error("not installed"));
    },
  };
});

const { default: BryntumTimeline } = await import("./BryntumTimeline.jsx");

const events = [
  {
    id: "dep-a",
    name: "La Rochelle",
    startDate: new Date("2026-11-12"),
    endDate: new Date("2026-11-13"),
    milestoneId: "dep-a",
  },
];

describe("BryntumTimeline import fallback", () => {
  it("falls back to the local list when lazy imports fail", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("fallback")).toBeInTheDocument();
  });
});

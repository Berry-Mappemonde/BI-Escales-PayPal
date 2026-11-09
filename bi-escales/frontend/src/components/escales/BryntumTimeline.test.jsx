import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import BryntumTimeline from "./BryntumTimeline.jsx";

vi.mock("@bryntum/scheduler-community", () => {
  throw new Error("not installed");
});

const events = [
  { id: "dep-a", name: "La Rochelle", startDate: new Date("2026-11-12"), endDate: new Date("2026-11-13"), milestoneId: "dep-a" },
];

describe("BryntumTimeline", () => {
  it("shows the loading line first", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("bryntum-loading")).toBeInTheDocument();
  });

  it("falls back to the local list when the package cannot load", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("fallback")).toBeInTheDocument();
  });

  it("uses the fallback when there are no events", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={[]} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });
});

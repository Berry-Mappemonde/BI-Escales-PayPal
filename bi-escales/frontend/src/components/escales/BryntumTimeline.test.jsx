import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../../i18n";
import BryntumTimeline, { bryntumLocaleForLanguage } from "./BryntumTimeline.jsx";

const events = [
  {
    id: "dep-a",
    name: "La Rochelle",
    startDate: new Date("2026-11-12"),
    endDate: new Date("2026-11-13"),
    milestoneId: "dep-a",
  },
];

describe("bryntumLocaleForLanguage", () => {
  it("maps French i18n to FrFr and English to En", () => {
    expect(bryntumLocaleForLanguage("fr")).toBe("FrFr");
    expect(bryntumLocaleForLanguage("fr-FR")).toBe("FrFr");
    expect(bryntumLocaleForLanguage("en")).toBe("En");
    expect(bryntumLocaleForLanguage("en-US")).toBe("En");
  });
});

describe("BryntumTimeline", () => {
  it("shows the loading line first", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("bryntum-loading")).toBeInTheDocument();
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

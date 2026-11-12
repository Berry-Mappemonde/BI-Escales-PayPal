/** Crew membership is the association membership (adhésion): 10 € per year. The copy says so, in both languages. */
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import en from "../i18n/locales/en.json";
import fr from "../i18n/locales/fr.json";
import { fetchCrewSupporterPlan } from "../api/escales";
import { CrewSupporterPublicSection } from "./CrewSubscribeButton";

vi.mock("../api/escales", async (load) => ({
  ...(await load<typeof import("../api/escales")>()),
  fetchCrewSupporterPlan: vi.fn(),
}));
vi.mock("../paypal/paypalSdk", async (load) => ({
  ...(await load<object>()),
  loadPayPalSubscriptionSdk: vi.fn(() => new Promise(() => {})),
}));

const strings = (node: unknown): string[] =>
  typeof node === "string" ? [node] : node && typeof node === "object" ? Object.values(node).flatMap(strings) : [];

describe("Crew membership copy", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-public-client");
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: "P-YEARLY", lang: "en" });
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  const show = () =>
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSupporterPublicSection />
      </I18nextProvider>,
    );

  it("says what it is and what it costs, beside the button", async () => {
    show();
    const section = await screen.findByTestId("crew-supporter-public");
    expect(section).toHaveTextContent("Crew membership");
    expect(section).toHaveTextContent("Association membership (adhésion) — 10 € per year");
  });

  it("says it in French", async () => {
    await i18n.changeLanguage("fr");
    show();
    const section = await screen.findByTestId("crew-supporter-public");
    expect(section).toHaveTextContent("Adhésion Crew");
    expect(section).toHaveTextContent("Adhésion à l’association — 10 € par an");
  });

  it("names the plan the treasurer creates as the Crew membership plan", () => {
    expect(en.treasurer.paypal.setupCrew).toBe("Ensure Crew membership plan (sandbox)");
    expect(en.pledge.crewSubscribePlanTreasurerHint).toContain("Ensure Crew membership plan (sandbox)");
    expect(en.pledge.crewSubscribePlanTreasurerHint).toContain("10 € per year");
    expect(fr.treasurer.paypal.setupCrew).toBe("Préparer le plan Adhésion Crew (bac à sable)");
    expect(fr.pledge.crewSubscribePlanTreasurerHint).toContain("10 € par an");
  });

  it.each([
    ["en", en],
    ["fr", fr],
  ])("has no trace of a monthly price or of the old names in %s", (_lang, locale) => {
    const crew = strings(locale).filter((text) => /crew|adhésion|équipage/i.test(text));
    expect(crew.length).toBeGreaterThan(10);
    for (const text of crew) {
      expect(text).not.toMatch(/monthly|per month|mensuel|par mois|5 €|5 EUR|Crew supporter|Abonnement Crew|plan Équipage|Soutien d/i);
    }
  });
});

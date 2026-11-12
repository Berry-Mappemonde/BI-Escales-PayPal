import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi, beforeEach } from "vitest";
import i18n from "../i18n";
import { fetchProjectOnboarding } from "../api/projectOnboarding";
import { ProjectOnboardingPage } from "./ProjectOnboardingPage";

vi.mock("../api/projectOnboarding", () => ({
  fetchOnboardingFeatureStatus: vi.fn().mockResolvedValue({ enabled: true, demo_project_id: "projet-berry-mappemonde" }),
  fetchProjectOnboarding: vi.fn().mockResolvedValue({
    id: "projet-berry-mappemonde",
    title: "Berry-Mappemonde association",
    description:
      "A French non-profit based in Saint-Maur (Indre), Berry-Mappemonde is organising a 36-month sailing expedition on production sailboats, linking the Berry, a landlocked region in the heart of France, to France's 13 overseas territories. The association builds lasting ties between these places (twinnings, exchanges, partnerships), runs school programmes, raises awareness of maritime, farming and environmental issues, and documents the journey through a book, a documentary series and a travelling exhibition.",
    image_url: "/static/onboarding/berry-mappemonde-logo.webp",
    location_label: "Saint-Maur (Indre), France",
    onboarding_status: "pending",
    donations: [
      {
        id: "d1",
        amount_eur: "10.00",
        status: "held_pending_onboarding",
        status_label_key: "projectOnboarding.status.held_pending_onboarding",
        deadline_at: "2026-12-10T12:00:00Z",
      },
    ],
    wallet_only: true,
    card_fields_hidden: true,
  }),
  createOnboardingDonation: vi.fn(),
  captureOnboardingDonation: vi.fn(),
}));

describe("ProjectOnboardingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("shows held pending onboarding label from i18n", async () => {
    i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectOnboardingPage projectId="projet-berry-mappemonde" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("project-onboarding-page")).toBeInTheDocument());
    expect(screen.getAllByText(/Held pending project onboarding/i).length).toBeGreaterThanOrEqual(1);
    expect(document.querySelector('li[data-status="held_pending_onboarding"]')).not.toBeNull();
    expect(screen.getByTestId("onboard-donate")).toBeInTheDocument();
    expect(screen.getByTestId("project-onboarding-logo")).toHaveAttribute(
      "src",
      "/static/onboarding/berry-mappemonde-logo.webp",
    );
    expect(screen.getByTestId("project-onboarding-location")).toHaveTextContent("Saint-Maur (Indre), France");
    expect(screen.getByText(/travelling exhibition\./)).toBeInTheDocument();
  });
});


it.each([ ["en", "This project was not found"], ["fr", "Ce projet est introuvable"] ])("shows a clear %s message for a missing project", async (lang, message) => {
  await i18n.changeLanguage(lang);
  vi.mocked(fetchProjectOnboarding).mockResolvedValueOnce(null);
  render(<I18nextProvider i18n={i18n}><ProjectOnboardingPage projectId="demo" /></I18nextProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByText(/Loading project|Chargement du projet/)).not.toBeInTheDocument();
});

it("shows a recoverable error when the project request fails", async () => {
  await i18n.changeLanguage("en");
  vi.mocked(fetchProjectOnboarding).mockRejectedValueOnce(new Error("unavailable"));
  render(<I18nextProvider i18n={i18n}><ProjectOnboardingPage projectId="demo" /></I18nextProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the project");
});

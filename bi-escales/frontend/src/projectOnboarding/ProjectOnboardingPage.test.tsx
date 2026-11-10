import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi, beforeEach } from "vitest";
import i18n from "../i18n";
import { ProjectOnboardingPage } from "./ProjectOnboardingPage";

vi.mock("../api/projectOnboarding", () => ({
  fetchOnboardingFeatureStatus: vi.fn().mockResolvedValue({ enabled: true, demo_project_id: "projet-demo-recif-vivant" }),
  fetchProjectOnboarding: vi.fn().mockResolvedValue({
    id: "projet-demo-recif-vivant",
    demo_fake: true,
    title: "Demo Project — Living Reef (fictional / sandbox)",
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
        <ProjectOnboardingPage projectId="projet-demo-recif-vivant" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("project-onboarding-page")).toBeInTheDocument());
    expect(screen.getAllByText(/Held pending project onboarding/i).length).toBeGreaterThanOrEqual(1);
    expect(document.querySelector('li[data-status="held_pending_onboarding"]')).not.toBeNull();
    expect(screen.getByTestId("onboard-donate")).toBeInTheDocument();
  });
});

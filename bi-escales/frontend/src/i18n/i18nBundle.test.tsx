import type { ReactNode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchCrewSupporterPlan, fetchPledgeMode } from "../api/escales";
import { CrewSubscribeButton } from "../components/CrewSubscribeButton";
import { PledgeButton } from "../components/PledgeButton";
import { StopStatusChip } from "../components/stop/StopStatusChip";
import i18n, { applyDocumentLang, setLanguage } from "./index";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "AUTHORIZE" }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false, wallet_pay: false }),
  fetchCrewSupporterPlan: vi.fn(),
  approveCrewSubscription: vi.fn(),
  recordSubscription: vi.fn(),
  isVaultPledge: () => false,
}));

const pledgeValues = {
  amount_eur: "20.00",
  description: "20 nautical miles",
  milestone_id: "dep-mayotte",
  kind: "mile",
  target_id: "dep-mayotte",
};

const FR_LEAKS = [
  /Pay Only If We Sail/i,
  /Payez seulement si nous partons/i,
  /\bAUTHORIZE\b/,
  /\bCAPTURE\b/,
  /\bVault\b/,
  /Intent AUTHORIZE/i,
];

const EN_LEAKS = [/\bEn route\b/, /Escale — arrivée/, /prix simulé/i];

function shell(children: ReactNode) {
  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}

function bodyText() {
  return document.body.textContent || "";
}

describe("I18N-BUNDLE leak guard", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
    await i18n.changeLanguage("fr");
    applyDocumentLang("fr");
  });

  afterEach(async () => {
    await i18n.changeLanguage("fr");
    applyDocumentLang("fr");
  });

  it.each(FR_LEAKS)("French UI does not show leak %s", async (pattern) => {
    await i18n.changeLanguage("fr");
    render(shell(<PledgeButton values={pledgeValues} />));
    await screen.findByText(fr.pledge.intent);
    expect(bodyText()).not.toMatch(pattern);
  });

  it.each(EN_LEAKS)("English UI does not show leak %s", async (pattern) => {
    await i18n.changeLanguage("en");
    render(
      shell(
        <>
          <StopStatusChip status="en_route" />
          <PledgeButton values={pledgeValues} />
        </>,
      ),
    );
    await screen.findByText(en.stopPanel.status.en_route);
    expect(bodyText()).not.toMatch(pattern);
  });
});

describe("I18N-BUNDLE language switch", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("fr");
    applyDocumentLang("fr");
  });

  it("updates document.documentElement.lang when the language changes", async () => {
    await act(async () => {
      setLanguage("en");
    });
    expect(document.documentElement.lang).toBe("en");
    await act(async () => {
      setLanguage("fr");
    });
    expect(document.documentElement.lang).toBe("fr");
  });

  it("reloads the Crew plan id when the language changes", async () => {
    vi.mocked(fetchCrewSupporterPlan)
      .mockResolvedValueOnce({ plan_id: "PLAN-FR" })
      .mockResolvedValueOnce({ plan_id: "PLAN-EN" });

    const { rerender } = render(shell(<CrewSubscribeButton />));
    await waitFor(() => expect(fetchCrewSupporterPlan).toHaveBeenCalledWith("fr"));
    await waitFor(() => expect(fetchCrewSupporterPlan).toHaveBeenCalledTimes(1));

    await act(async () => {
      await i18n.changeLanguage("en");
    });
    rerender(shell(<CrewSubscribeButton />));
    await waitFor(() => expect(fetchCrewSupporterPlan).toHaveBeenCalledWith("en"));
    expect(fetchCrewSupporterPlan).toHaveBeenCalledTimes(2);
  });
});

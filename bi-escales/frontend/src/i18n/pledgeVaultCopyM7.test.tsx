import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./index";
import en from "./locales/en.json";
import fr from "./locales/fr.json";
import { PledgeButton } from "../components/PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "VAULT" }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false }),
  isVaultPledge: () => true,
}));

const values = {
  amount_eur: "20.00",
  description: "20 nm",
  milestone_id: "dep-la-rochelle",
  kind: "mile",
  target_id: "dep-la-rochelle",
};

const LEGACY_EN = /charged only if we sail|only if we sail/i;
const LEGACY_FR = /si nous appareillons|si nous partons/i;

/** Mutation M7: vault / intent copy must describe arrival capture, not departure/sail. */
describe("M7 vault arrival copy guard", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("keeps locale bundles free of legacy sail / appareillons wording on vault keys", () => {
    expect(en.pledge.intentVault).toMatch(/captured on arrival/i);
    expect(en.pledge.vaultSaved).toMatch(/captured on arrival/i);
    expect(en.pledge.intentVault).not.toMatch(LEGACY_EN);
    expect(en.pledge.vaultSaved).not.toMatch(LEGACY_EN);

    expect(fr.pledge.intentVault).toMatch(/arrivée du bateau/i);
    expect(fr.pledge.vaultSaved).toMatch(/arrivée du bateau/i);
    expect(fr.pledge.intentVault).toMatch(/escale est annulée/i);
    expect(fr.pledge.vaultSaved).toMatch(/escale est annulée/i);
    expect(fr.pledge.intentVault).not.toMatch(LEGACY_FR);
    expect(fr.pledge.vaultSaved).not.toMatch(LEGACY_FR);
  });

  it.each([
    ["en", en.pledge.intentVault, /captured on arrival/i, LEGACY_EN],
    ["fr", fr.pledge.intentVault, /arrivée du bateau/i, LEGACY_FR],
  ] as const)("renders %s VAULT checkout copy with arrival capture wording", async (lang, expected, mustMatch, mustNot) => {
    await i18n.changeLanguage(lang);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    const line = await screen.findByText(expected);
    expect(line).toBeInTheDocument();
    expect(line.textContent).toMatch(mustMatch);
    expect(line.textContent).not.toMatch(mustNot);
  });
});

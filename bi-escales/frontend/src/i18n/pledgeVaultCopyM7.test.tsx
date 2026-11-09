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

const LEGACY_EN = /charged only if we sail|only if we sail|until we sail/i;
const LEGACY_FR = /si nous appareillons|si nous partons|ne partons pas/i;

const VAULT_ARRIVAL_KEYS = ["intentVault", "vaultSaved", "vaultHint"] as const;

/** Mutation M7: vault / intent copy must describe arrival capture, not departure/sail. */
describe("M7 vault arrival copy guard", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("keeps locale bundles free of legacy sail / partons wording on vault keys", () => {
    for (const key of VAULT_ARRIVAL_KEYS) {
      const enLine = en.pledge[key];
      const frLine = fr.pledge[key];
      expect(enLine).toMatch(/captured on arrival/i);
      expect(enLine).not.toMatch(LEGACY_EN);
      expect(frLine).toMatch(/arrivée du bateau/i);
      expect(frLine).toMatch(/escale est annulée/i);
      expect(frLine).not.toMatch(LEGACY_FR);
    }
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

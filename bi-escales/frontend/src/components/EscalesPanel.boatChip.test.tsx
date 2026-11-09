import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { EscalesPanel } from "./EscalesPanel";

vi.mock("../api/escales", () => ({
  captainChat: vi.fn(),
  createPayPalInvoice: vi.fn(),
}));

describe("EscalesPanel boat chip", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("fr");
  });

  it.each([
    ["fr", "Où est le bateau ?"],
    ["en", "Where is the boat?"],
  ])("calls onLocateBoat on click and keyboard in %s", async (lang, label) => {
    await i18n.changeLanguage(lang);
    const onLocateBoat = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-la-rochelle" onLocateBoat={onLocateBoat} />
      </I18nextProvider>,
    );
    const chip = screen.getByRole("button", { name: label });
    fireEvent.click(chip);
    expect(onLocateBoat).toHaveBeenCalledTimes(1);
    onLocateBoat.mockClear();
    chip.focus();
    await userEvent.keyboard("{Enter}");
    expect(onLocateBoat).toHaveBeenCalledTimes(1);
    onLocateBoat.mockClear();
    await userEvent.keyboard(" ");
    expect(onLocateBoat).toHaveBeenCalledTimes(1);
  });
});

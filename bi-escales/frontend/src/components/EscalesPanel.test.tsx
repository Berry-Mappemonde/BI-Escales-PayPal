import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { captainChat } from "../api/escales";
import i18n from "../i18n";
import { EscalesPanel } from "./EscalesPanel";

vi.mock("../api/escales", () => ({
  captainChat: vi.fn(),
  createPledge: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "AUTHORIZE" }),
  fetchFeatures: vi.fn().mockResolvedValue({ vault: true }),
}));

describe("EscalesPanel cart", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("fr");
  });

  it.each([
    ["fr", "20 milles près de Mayotte", "Demander au capitaine"],
    ["en", "Sponsor 20 miles near Mayotte", "Ask the Captain"],
  ])("starts empty with a localized placeholder in %s and refuses blank submissions", async (lang, placeholder, action) => {
    await i18n.changeLanguage(lang);
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    const input = screen.getByRole("textbox");
    expect(screen.getByRole("heading", { name: lang === "en" ? "Ask the AI Captain" : "Poser une question au capitaine IA" })).toBeInTheDocument();
    expect(input).toHaveAccessibleName(lang === "en" ? "Your question" : "Votre question");
    expect(screen.getByText(lang === "en" ? "When am I charged?" : "Quand suis-je débité ?")).toBeInTheDocument();
    expect(screen.getByText(lang === "en" ? "What happens if a stop is cancelled?" : "Que se passe-t-il si une escale est annulée ?")).toBeInTheDocument();
    expect(screen.getByText(lang === "en" ? "Where is the boat?" : "Où est le bateau ?")).toBeInTheDocument();
    const prompts = screen.getByRole("list", { name: lang === "en" ? "Example questions" : "Exemples de questions" });
    expect(prompts.querySelectorAll("li")).toHaveLength(3);
    // Every example is a real control: the first two fill the field without sending.
    expect(prompts.querySelectorAll("li > button")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: lang === "en" ? "When am I charged?" : "Quand suis-je débité ?" }));
    expect(input).toHaveValue(lang === "en" ? "When am I charged?" : "Quand suis-je débité ?");
    expect(captainChat).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "" } });
    const button = screen.getByRole("button", { name: action });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", placeholder);
    expect(button).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(captainChat).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "  \n " } });
    expect(button).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(captainChat).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "Sponsor 5 miles" } });
    expect(button).toBeEnabled();
    fireEvent.change(input, { target: { value: "" } });
    expect(button).toBeDisabled();
  });

  it("affiche chaque ligne et son objet pledge", async () => {
    vi.mocked(captainChat).mockResolvedValue({
      reply: "Promesse calculée.",
      suggested_pledge: {
        amount_eur: "20.00",
        currency: "EUR",
        description: "20 milles parrainés",
        milestone_id: "dep-mayotte",
        intent: "AUTHORIZE",
      },
      cart: {
        currency: "EUR",
        lines: [
          {
            kind: "mile",
            description: "20 milles parrainés",
            amount_eur: "20.00",
            price_label: "simulation",
            pledge: {
              amount_eur: "20.00",
              description: "20 milles parrainés",
              milestone_id: "dep-mayotte",
              kind: "mile",
              target_id: "dep-mayotte",
            },
          },
        ],
      },
    });

    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "20 milles près de Mayotte" } });
    fireEvent.click(screen.getByRole("button", { name: "Demander au capitaine" }));
    expect(captainChat).toHaveBeenCalledWith("20 milles près de Mayotte", "fr", undefined);
    const line = await screen.findByTestId("cart-line");
    expect(line).toHaveTextContent("20 milles parrainés — 20.00 EUR");
    expect(line).toHaveTextContent("prix simulé");
    expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-kind", "mile");
    expect(screen.queryByTestId("pledge-authorize")).toBeNull();
    expect(screen.queryByRole("button", { name: /preuve/i })).toBeNull();
  });

  it("shows PayPal tools called under the captain reply", async () => {
    vi.mocked(captainChat).mockResolvedValue({
      reply: "Read-only summary.",
      model_label: "NVIDIA NIM — test",
      paypal_tools: {
        tools: ["transactions.search"],
        called: ["transactions.search"],
        client: "paypal-agent-toolkit",
      },
    });
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "20 milles près de Mayotte" } });
    fireEvent.click(screen.getByRole("button", { name: "Demander au capitaine" }));
    const line = await screen.findByTestId("captain-paypal-tools");
    expect(line).toHaveTextContent("transactions.search");
    expect(line).toHaveTextContent("paypal-agent-toolkit");
  });

  it("affiche un message convivial sur HTTP 429", async () => {
    vi.mocked(captainChat).mockRejectedValue(
      new Error("Too many requests. The captain accepts 2 per minute."),
    );
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "20 milles près de Mayotte" } });
    fireEvent.click(screen.getByRole("button", { name: "Demander au capitaine" }));
    expect(await screen.findByText(/Trop de requêtes vers le capitaine/)).toBeInTheDocument();
  });
});

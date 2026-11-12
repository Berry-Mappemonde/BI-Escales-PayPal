/** Audit item 2: after an answer, the question asked stays above it and the example questions stay available. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  fetchFeatures: vi.fn().mockResolvedValue({}),
}));

const reply = (text: string) => ({ reply: text, suggested_pledge: null, cart: null, rule_by_design: true, model_source: { provider: "rules", model: "" } }) as never;
const show = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <EscalesPanel milestoneId="dep-la-rochelle" />
    </I18nextProvider>,
  );
const send = () => fireEvent.submit(screen.getByRole("textbox").closest("form") as HTMLFormElement);
const chips = () => screen.getByRole("list", { name: i18n.t("escales.exampleQuestions") });

describe("EscalesPanel after an answer", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("shows the question above the reply it answers", async () => {
    vi.mocked(captainChat).mockResolvedValue(reply("Stop-level pledges are captured on arrival."));
    show();
    fireEvent.click(screen.getByRole("button", { name: "When am I charged?" }));
    send();
    expect(await screen.findByTestId("captain-question")).toHaveTextContent("You asked: When am I charged?");
    expect(screen.getByText("Stop-level pledges are captured on arrival.")).toBeInTheDocument();
  });

  it("keeps the example questions, so the next one is one click away", async () => {
    vi.mocked(captainChat).mockResolvedValue(reply("First answer."));
    show();
    fireEvent.click(screen.getByRole("button", { name: "When am I charged?" }));
    send();
    await screen.findByText("First answer.");
    // Every example question is still there (their number is not this test's subject).
    expect(chips().querySelectorAll("li").length).toBeGreaterThanOrEqual(3);

    vi.mocked(captainChat).mockResolvedValue(reply("Second answer."));
    fireEvent.click(screen.getByRole("button", { name: "What happens if a stop is cancelled?" }));
    // The field changed, the reply on screen still says which question it answers.
    expect(screen.getByTestId("captain-question")).toHaveTextContent("You asked: When am I charged?");
    send();
    await screen.findByText("Second answer.");
    expect(screen.getByTestId("captain-question")).toHaveTextContent("You asked: What happens if a stop is cancelled?");
    expect(vi.mocked(captainChat).mock.calls.map((call) => call[0])).toEqual(["When am I charged?", "What happens if a stop is cancelled?"]);
  });

  it("hides the examples only while the Captain is answering", async () => {
    let finish!: (value: never) => void;
    vi.mocked(captainChat).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    show();
    fireEvent.click(screen.getByRole("button", { name: "When am I charged?" }));
    send();
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.queryByRole("list", { name: "Example questions" })).toBeNull();
    finish(reply("Done."));
    await screen.findByText("Done.");
    expect(chips()).toBeInTheDocument();
  });

  it("shows no question line before anything was asked, or when the request failed", async () => {
    vi.mocked(captainChat).mockRejectedValue(new Error("Captain unavailable"));
    show();
    expect(screen.queryByTestId("captain-question")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "When am I charged?" }));
    send();
    expect(await screen.findByText("Captain unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("captain-question")).toBeNull();
    expect(chips()).toBeInTheDocument();
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(captainChat).mockResolvedValue(reply("Réponse."));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Quand suis-je débité ?" }));
    send();
    expect(await screen.findByTestId("captain-question")).toHaveTextContent("Votre question : Quand suis-je débité ?");
  });
});

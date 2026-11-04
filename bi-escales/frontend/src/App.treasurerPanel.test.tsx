import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: () => ({
    pledges: [],
    loading: false,
    error: null,
    needsKey: true,
    refresh: vi.fn(),
    updatePledge: vi.fn(),
  }),
}));

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false }),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    settleClock: vi.fn(),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/CrewSubscribeButton", () => ({ CrewSubscribeButton: () => null }));
vi.mock("./marinas/escaleFiche.js", () => ({ loadEscaleFiche: vi.fn(), ficheMarinas: vi.fn(() => []) }));

describe("Crew subscription return handling", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "http://localhost/",
    });
    vi.stubGlobal("history", {
      ...window.history,
      replaceState: vi.fn(),
    });
  });

  it("shows a confirmation when PayPal returns with ?sub=return", async () => {
    vi.stubGlobal("location", {
      ...window.location,
      search: "?sub=return",
      pathname: "/",
      href: "http://localhost/?sub=return",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    expect(await screen.findByTestId("crew-subscribe-return-notice")).toHaveTextContent(/confirmed/i);
  });
});

describe("Treasurer panel (mini-mix lot 1)", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.removeItem("bi-escales-lang");
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "http://localhost/",
    });
    vi.stubGlobal("history", {
      ...window.history,
      replaceState: vi.fn(),
    });
  });

  it("keeps treasurer tools collapsed by default on the public map", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const toggle = screen.getByTestId("treasurer-panel-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "treasurer-panel-body");
    expect(screen.queryByTestId("treasurer-panel-body")).toBeNull();
    expect(screen.queryByTestId("admin-key-input")).toBeNull();
    expect(screen.queryByTestId("departure-settle")).toBeNull();
  });

  it("uses a masked admin key field and does not persist it to storage", async () => {
    const user = userEvent.setup();
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    await user.click(screen.getByTestId("treasurer-panel-toggle"));
    const keyInput = screen.getByTestId("admin-key-input");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(keyInput).toHaveAttribute("autocomplete", "off");

    await user.type(keyInput, "secret-admin-key");
    const persistedAdmin = storageSpy.mock.calls.some(
      ([, value]) => typeof value === "string" && value.includes("secret-admin"),
    );
    expect(persistedAdmin).toBe(false);
    storageSpy.mockRestore();
  });

  it("opens treasurer tools when the #tresorier hash is used", async () => {
    vi.stubGlobal("location", {
      ...window.location,
      hash: "#tresorier",
      href: "http://localhost/#tresorier",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("treasurer-panel-toggle")).toHaveAttribute("aria-expanded", "true");
    });
    expect(screen.getByTestId("admin-key-input")).toBeInTheDocument();
    expect(screen.getByTestId("departure-settle")).toBeDisabled();
  });

  it("clears #tresorier from the URL when the panel is closed", async () => {
    const user = userEvent.setup();
    const replaceState = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      hash: "#tresorier",
      pathname: "/",
      search: "",
      href: "http://localhost/#tresorier",
    });
    vi.stubGlobal("history", { ...window.history, replaceState });

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("treasurer-panel-toggle")).toHaveAttribute("aria-expanded", "true");
    });
    await user.click(screen.getByTestId("treasurer-panel-toggle"));
    expect(replaceState).toHaveBeenCalledWith({}, "", "/");
  });
});

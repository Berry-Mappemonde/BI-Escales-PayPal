import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { DemoStopMoment } from "./DemoStopMoment";

vi.mock("../api/escales", () => ({
  demoSimulateArrival: vi.fn(),
  demoCancelStop: vi.fn(),
  demoResetStop: vi.fn(),
}));

import { demoCancelStop, demoResetStop, demoSimulateArrival } from "../api/escales";

describe("DemoStopMoment", () => {
  const refresh = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(demoSimulateArrival).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      actions: [{ pledge_id: "p-1", action: "capture", capture_id: "CAP-123" }],
    });
    vi.mocked(demoCancelStop).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      actions: [{ pledge_id: "p-2", action: "void", void_id: "VOID-456" }],
    });
    vi.mocked(demoResetStop).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      actions: [],
    });
  });


  it("shows a working message while PayPal processes the pledges", async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage("en");
    let finish: (value: { milestone_id: string; actions: [] }) => void = () => undefined;
    vi.mocked(demoSimulateArrival).mockImplementation(
      () => new Promise((resolve) => { finish = resolve; }),
    );
    render(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment adminKey="tk" onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("demo-stop-working")).toBeNull();
    await user.click(screen.getByTestId("demo-stop-simulate-arrival"));
    expect(await screen.findByTestId("demo-stop-working")).toHaveTextContent(/up to a minute/i);
    finish({ milestone_id: "dep-la-rochelle", actions: [] });
    await waitFor(() => expect(screen.queryByTestId("demo-stop-working")).toBeNull());
  });

  it("names the stop, not its id, in both languages", async () => {
    for (const lang of ["en", "fr"]) {
      await i18n.changeLanguage(lang);
      const { unmount } = render(
        <I18nextProvider i18n={i18n}>
          <DemoStopMoment adminKey="tk" onRefresh={refresh} />
        </I18nextProvider>,
      );
      const section = screen.getByTestId("demo-stop-moment");
      expect(section).toHaveTextContent("La Rochelle");
      expect(section).not.toHaveTextContent("dep-la-rochelle");
      unmount();
    }
  });

  it("shows FR and EN labels and wires actions", async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage("fr");
    const { rerender } = render(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment adminKey="tk" onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-moment")).toBeInTheDocument();
    expect(screen.getByTestId("demo-stop-simulate-arrival")).toHaveTextContent(/arrivée du bateau/i);
    await user.click(screen.getByTestId("demo-stop-simulate-arrival"));
    await waitFor(() => expect(demoSimulateArrival).toHaveBeenCalledWith("dep-la-rochelle", "tk"));
    expect(screen.getByTestId("demo-stop-settle-note")).toHaveTextContent("CAP-123");
    expect(refresh).toHaveBeenCalled();

    await i18n.changeLanguage("en");
    rerender(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment adminKey="tk" onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-cancel")).toHaveTextContent(/Cancel stop/i);
    await user.click(screen.getByTestId("demo-stop-cancel"));
    await waitFor(() => expect(demoCancelStop).toHaveBeenCalled());
    expect(screen.getByTestId("demo-stop-settle-note")).toHaveTextContent("VOID-456");
  });

  it("disables the judge-moment buttons without a treasurer key", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment adminKey="" onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-simulate-arrival")).toBeDisabled();
    expect(screen.getByTestId("demo-stop-cancel")).toBeDisabled();
    expect(screen.getByTestId("demo-stop-reset")).toBeDisabled();
    expect(demoSimulateArrival).not.toHaveBeenCalled();
  });
});

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


  it("shows FR and EN labels and wires actions", async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage("fr");
    const { rerender } = render(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-moment")).toBeInTheDocument();
    expect(screen.getByTestId("demo-stop-simulate-arrival")).toHaveTextContent(/arrivée du bateau/i);
    await user.click(screen.getByTestId("demo-stop-simulate-arrival"));
    await waitFor(() => expect(demoSimulateArrival).toHaveBeenCalledWith("dep-la-rochelle"));
    expect(screen.getByTestId("demo-stop-settle-note")).toHaveTextContent("CAP-123");
    expect(refresh).toHaveBeenCalled();

    await i18n.changeLanguage("en");
    rerender(
      <I18nextProvider i18n={i18n}>
        <DemoStopMoment onRefresh={refresh} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-cancel")).toHaveTextContent(/Cancel stop/i);
    await user.click(screen.getByTestId("demo-stop-cancel"));
    await waitFor(() => expect(demoCancelStop).toHaveBeenCalled());
    expect(screen.getByTestId("demo-stop-settle-note")).toHaveTextContent("VOID-456");
  });
});

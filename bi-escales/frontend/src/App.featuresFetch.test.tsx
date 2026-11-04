import { render, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import * as escalesApi from "./api/escales";

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof escalesApi>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue(undefined),
    fetchFeatures: vi.fn().mockResolvedValue({ bryntum: false, clock_pinned: true }),
    fetchSchedule: vi.fn().mockResolvedValue({ milestones: [] }),
    fetchFund: vi.fn(),
    fetchCrewSupporterPlan: vi.fn().mockResolvedValue({ plan_id: "PLAN-TEST" }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    recordSpending: vi.fn(),
    settleClock: vi.fn(),
    approveCrewSubscription: vi.fn(),
  };
});

vi.mock("./map/MapScene", () => ({ MapScene: () => null }));
vi.mock("./components/escales/EscalesScheduler", () => ({ EscalesScheduler: () => null }));
vi.mock("./components/MarinasPanel", () => ({ MarinasPanel: () => null }));

import App from "./App";

describe("App features fetch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads /features once on mount (N30)", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(vi.mocked(escalesApi.fetchFeatures)).toHaveBeenCalledTimes(1);
    });
  });
});

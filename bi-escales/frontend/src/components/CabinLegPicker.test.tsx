import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n";
import { fetchSchedule } from "../api/escales";
import { CabinLegPicker } from "./CabinLegPicker";

vi.mock("../api/escales", () => ({
  fetchSchedule: vi.fn(),
}));

const legs = [
  {
    id: "leg-la-rochelle-to-ajaccio-corse",
    from_name: "La Rochelle",
    to_name: "Ajaccio (Corse)",
    departure_iso: "2026-11-12T12:00:00Z",
  },
  {
    id: "leg-ajaccio-corse-to-fort-de-france-martinique",
    from_name: "Ajaccio (Corse)",
    to_name: "Fort-de-France (Martinique)",
    departure_iso: "2026-12-02T10:00:00Z",
  },
];

describe("CabinLegPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchSchedule).mockResolvedValue({ legs });
  });

  it("lists legs from GET /api/escales/schedule", async () => {
    const onChange = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <CabinLegPicker value="" onChange={onChange} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("cabin-leg-picker-loading")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("cabin-leg-picker")).toBeInTheDocument());
    expect(fetchSchedule).toHaveBeenCalledTimes(1);
    const options = screen.getAllByTestId("cabin-leg-option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveAttribute("data-leg-id", legs[0].id);
    await userEvent.click(options[1]);
    expect(onChange).toHaveBeenCalledWith(legs[1].id);
  });

  it("shows empty state when schedule has no legs", async () => {
    vi.mocked(fetchSchedule).mockResolvedValue({ legs: [] });
    render(
      <I18nextProvider i18n={i18n}>
        <CabinLegPicker value="" onChange={vi.fn()} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("cabin-leg-picker-empty")).toBeInTheDocument());
  });
});

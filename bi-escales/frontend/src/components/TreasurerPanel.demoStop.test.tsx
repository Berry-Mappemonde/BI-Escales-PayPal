import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { TreasurerPanel } from "./TreasurerPanel";

const baseProps = {
  open: true,
  onOpenChange: vi.fn(),
  adminKey: "",
  onAdminKeyChange: vi.fn(),
  settleBusy: false,
  settleNote: null,
  onSettle: vi.fn(),
  clockPinned: false,
  settleAt: "",
  onSettleAtChange: vi.fn(),
  onSettleAt: vi.fn(),
  milestoneId: "dep-la-rochelle",
  onMilestoneIdChange: vi.fn(),
  projectFund: null,
  boatFund: null,
  pledges: [],
  loading: false,
  error: null,
  needsKey: true,
  onRefreshQueue: vi.fn(),
  onPledgeUpdated: vi.fn(),
  spendAmount: "",
  onSpendAmountChange: vi.fn(),
  spendNote: "",
  onSpendNoteChange: vi.fn(),
  spendError: null,
  fund: null,
  onSpendSubmit: vi.fn((event) => event.preventDefault()),
};

describe("TreasurerPanel demo stop moment", () => {
  it("hides judge-moment buttons when demo treasurer mode is off", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPanel {...baseProps} demoMode={false} />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("demo-stop-moment")).toBeNull();
  });

  it("shows judge-moment controls in demo treasurer mode", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPanel {...baseProps} demoMode needsKey={false} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("demo-stop-moment")).toBeInTheDocument();
    expect(screen.getByTestId("demo-stop-simulate-arrival")).toBeInTheDocument();
  });
});

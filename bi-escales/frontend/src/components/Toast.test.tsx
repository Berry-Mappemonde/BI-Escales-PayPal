import { fireEvent, render, screen, act } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { ToastContainer, type ToastItem } from "./Toast";

describe("Toast component", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.useRealTimers();
    await i18n.changeLanguage("en");
  });

  it("renders toast with title, detail, status icon, and dismiss button", () => {
    const items: ToastItem[] = [
      {
        id: "t-1",
        title: "Pledge authorized",
        detail: "Held on PayPal",
        variant: "held",
        testId: "toast-held-pledge",
      },
    ];
    const onDismiss = vi.fn();

    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={onDismiss} />
      </I18nextProvider>,
    );

    const toast = screen.getByTestId("toast-held-pledge");
    expect(toast).toBeInTheDocument();
    expect(toast).toHaveAttribute("role", "status");
    expect(toast).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Pledge authorized")).toBeInTheDocument();
    expect(screen.getByText("Held on PayPal")).toBeInTheDocument();

    const dismissBtn = screen.getByTestId("dismiss-notices");
    expect(dismissBtn).toHaveAttribute("aria-label", "Dismiss");
  });

  it("sets aria-live assertive for error toasts", () => {
    const items: ToastItem[] = [
      {
        id: "err-1",
        title: "Payment failed",
        variant: "error",
        testId: "toast-err",
      },
    ];
    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={vi.fn()} />
      </I18nextProvider>,
    );

    const toast = screen.getByTestId("toast-err");
    expect(toast).toHaveAttribute("aria-live", "assertive");
  });

  it("renders French aria-label when language is fr", async () => {
    await i18n.changeLanguage("fr");
    const items: ToastItem[] = [
      {
        id: "t-fr",
        title: "Promesse autorisée",
        variant: "held",
      },
    ];
    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={vi.fn()} />
      </I18nextProvider>,
    );

    const dismissBtn = screen.getByTestId("dismiss-notices");
    expect(dismissBtn).toHaveAttribute("aria-label", "Fermer");
  });

  it("dismisses on click", async () => {
    const onDismiss = vi.fn();
    const items: ToastItem[] = [
      {
        id: "t-click",
        title: "Pledge created",
        variant: "info",
      },
    ];
    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={onDismiss} />
      </I18nextProvider>,
    );

    const dismissBtn = screen.getByTestId("dismiss-notices");
    fireEvent.click(dismissBtn);

    // After animation end or timeout fallback
    await vi.waitFor(() => {
      expect(onDismiss).toHaveBeenCalledWith("t-click");
    });
  });

  it("auto-dismisses after 6s for info/success/held", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const items: ToastItem[] = [
      {
        id: "t-auto",
        title: "Saved — charged on arrival",
        variant: "success",
      },
    ];

    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={onDismiss} />
      </I18nextProvider>,
    );

    expect(onDismiss).not.toHaveBeenCalled();

    // Fast-forward 5.9s
    act(() => {
      vi.advanceTimersByTime(5900);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Fast-forward past 6s + 130ms exit animation
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onDismiss).toHaveBeenCalledWith("t-auto");
  });

  it("does not auto-dismiss error toasts", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const items: ToastItem[] = [
      {
        id: "t-err-stay",
        title: "Backend unreachable",
        variant: "error",
      },
    ];

    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={onDismiss} />
      </I18nextProvider>,
    );

    // Fast forward 10 seconds
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("pauses auto-dismiss timer on hover and resumes on leave", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const items: ToastItem[] = [
      {
        id: "t-hover",
        title: "Pledge authorized",
        variant: "held",
        testId: "toast-hover-item",
      },
    ];

    render(
      <I18nextProvider i18n={i18n}>
        <ToastContainer items={items} onDismiss={onDismiss} />
      </I18nextProvider>,
    );

    const toast = screen.getByTestId("toast-hover-item");

    // Advance 3 seconds
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // Hover
    fireEvent.mouseEnter(toast);

    // Advance another 5 seconds while hovered
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Leave
    fireEvent.mouseLeave(toast);

    // Needs ~3s remaining + 130ms exit to dismiss
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(onDismiss).toHaveBeenCalledWith("t-hover");
  });
});

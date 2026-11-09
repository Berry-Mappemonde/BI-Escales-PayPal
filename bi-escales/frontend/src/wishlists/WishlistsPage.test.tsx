import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import { buildPublicWishlist } from "./fixtures";
import { WishlistsPage } from "./WishlistsPage";

vi.mock("../components/PledgeButton", () => ({
  PledgeButton: () => <div data-testid="pledge-button" />,
}));

vi.mock("../hooks/useTheme", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

describe("WishlistsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders at least ten items with funding bars where applicable", async () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
    vi.spyOn(escalesApi, "fetchPublicWishlists").mockResolvedValue({
      wishlists: [buildPublicWishlist(12)],
    });
    render(<WishlistsPage />);
    await waitFor(() => {
      expect(screen.getAllByTestId("wishlist-item-card")).toHaveLength(12);
    });
    expect(screen.getAllByTestId("wishlist-funding-bar").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("wishlist-fund-block").length).toBeGreaterThan(0);
  });

  it("hides content when wishlists flag is off", async () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: false });
    const wl = vi.spyOn(escalesApi, "fetchPublicWishlists");
    render(<WishlistsPage />);
    await waitFor(() => {
      expect(screen.getByText(/ne sont pas activées|not enabled/i)).toBeInTheDocument();
    });
    expect(wl).not.toHaveBeenCalled();
  });
});

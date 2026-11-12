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

  it("gives each list an anchor and opens on the list the link names", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(null, "", "/escales/wishlists#wishlist-crew-gear");
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
    vi.spyOn(escalesApi, "fetchPublicWishlists").mockResolvedValue({
      wishlists: [
        { ...buildPublicWishlist(1), wishlist_id: "w-1", slug: "boat-gear", title: "Boat gear" },
        { ...buildPublicWishlist(1), wishlist_id: "w-2", slug: "crew-gear", title: "Crew gear" },
      ],
    });
    render(<WishlistsPage />);
    const sections = await screen.findAllByTestId("wishlist-section");
    expect(sections.map((section) => section.id)).toEqual(["wishlist-boat-gear", "wishlist-crew-gear"]);
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
    expect(scroll.mock.contexts[0]).toBe(sections[1]);
    window.history.replaceState(null, "", "/");
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

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as escalesApi from "../api/escales";
import { fixtureCatalogEur, fixtureTreasurerWishlist } from "./fixtures";
import { TreasurerWishlistsPanel } from "./TreasurerWishlistsPanel";

describe("TreasurerWishlistsPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a wishlist via POST /treasurer/wishlists", async () => {
    const user = userEvent.setup();
    const create = vi.spyOn(escalesApi, "createTreasurerWishlist").mockResolvedValue({
      _id: "wid-new",
      title: "New",
      slug: "new-slug",
      published: false,
      items: [],
    });
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 0, items: [] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [] });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await user.type(screen.getByTestId("wishlist-create-title"), "New");
    await user.type(screen.getByTestId("wishlist-create-slug"), "new-slug");
    await user.click(screen.getByTestId("wishlist-create-submit"));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith("test-key", { title: "New", slug: "new-slug", items: [] }),
    );
  });

  it("adds, removes, and publishes on an existing list", async () => {
    const user = userEvent.setup();
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({
      item_count: 1,
      items: [fixtureCatalogEur],
    });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [fixtureTreasurerWishlist] });
    const add = vi.spyOn(escalesApi, "addTreasurerWishlistItem").mockResolvedValue(fixtureTreasurerWishlist);
    const remove = vi.spyOn(escalesApi, "removeTreasurerWishlistItem").mockResolvedValue({
      ...fixtureTreasurerWishlist,
      items: [],
    });
    const publish = vi
      .spyOn(escalesApi, "publishTreasurerWishlist")
      .mockResolvedValueOnce({ ...fixtureTreasurerWishlist, published: true })
      .mockResolvedValueOnce({ ...fixtureTreasurerWishlist, published: false });

    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await waitFor(() => expect(screen.getByTestId("wishlist-treasurer-select")).toBeInTheDocument());

    await user.selectOptions(screen.getByTestId("wishlist-catalog-pick"), fixtureCatalogEur.channel3_product_id);
    await user.click(screen.getByTestId("wishlist-add-submit"));
    await waitFor(() => expect(add).toHaveBeenCalled());

    await user.click(screen.getByTestId(`wishlist-remove-${fixtureCatalogEur.channel3_product_id}`));
    await waitFor(() => expect(remove).toHaveBeenCalled());

    await user.click(screen.getByTestId("wishlist-publish"));
    await waitFor(() => expect(publish).toHaveBeenCalledWith("test-key", fixtureTreasurerWishlist._id, true));

    await user.click(screen.getByTestId("wishlist-unpublish"));
    await waitFor(() =>
      expect(publish).toHaveBeenLastCalledWith("test-key", fixtureTreasurerWishlist._id, false),
    );
  });

  it("shows unavailable line when catalogue lacks a stored product id", async () => {
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 1, items: [fixtureCatalogEur] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [fixtureTreasurerWishlist] });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await waitFor(() => {
      expect(screen.getByTestId("wishlist-item-unavailable")).toBeInTheDocument();
    });
  });
});

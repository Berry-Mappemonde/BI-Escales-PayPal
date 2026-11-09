import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addTreasurerWishlistItem,
  createTreasurerWishlist,
  fetchChannel3Catalog,
  fetchPublicWishlists,
  publishTreasurerWishlist,
  removeTreasurerWishlistItem,
} from "../api/escales";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("channel3 wishlist API client", () => {
  it("hits public catalog and wishlist routes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ item_count: 2, items: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ wishlists: [] }),
      });
    vi.stubGlobal("fetch", fetchMock);
    await fetchChannel3Catalog();
    await fetchPublicWishlists();
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/escales\/channel3\/catalog$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/api\/escales\/wishlists$/);
  });

  it("sends treasurer headers and bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ _id: "wid", items: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await createTreasurerWishlist("secret", { title: "T", slug: "s", items: [] });
    await addTreasurerWishlistItem("secret", "wid", {
      channel3_product_id: "mock-prod-eur-01",
      quantity: 2,
    });
    await removeTreasurerWishlistItem("secret", "wid", "mock-prod-eur-01");
    await publishTreasurerWishlist("secret", "wid", true);
    const headers = (init: RequestInit | undefined) => (init?.headers || {}) as Record<string, string>;
    expect(headers(fetchMock.mock.calls[0][1])["x-admin-key"]).toBe("secret");
    expect(fetchMock.mock.calls[2][0]).toMatch(/\/items\/mock-prod-eur-01$/);
    expect(fetchMock.mock.calls[3][0]).toMatch(/\/publish$/);
  });
});

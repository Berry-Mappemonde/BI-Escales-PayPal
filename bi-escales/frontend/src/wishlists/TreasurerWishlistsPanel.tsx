import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  addTreasurerWishlistItem,
  createTreasurerWishlist,
  fetchChannel3Catalog,
  fetchTreasurerWishlists,
  publishTreasurerWishlist,
  removeTreasurerWishlistItem,
} from "../api/escales";
import type { Channel3CatalogItem, TreasurerWishlistDoc } from "../api/types";
import { catalogMapFromItems, linesFromTreasurerItems } from "./catalogMap";
import { WishlistItemUnavailable } from "./WishlistItemCard";

export interface TreasurerWishlistsPanelProps {
  adminKey: string;
}

export function TreasurerWishlistsPanel({ adminKey }: TreasurerWishlistsPanelProps) {
  const { t } = useTranslation();
  const key = adminKey.trim();
  const [catalog, setCatalog] = useState<Channel3CatalogItem[]>([]);
  const [wishlists, setWishlists] = useState<TreasurerWishlistDoc[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [pickProductId, setPickProductId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [targetMinor, setTargetMinor] = useState("");
  const [allowOptional, setAllowOptional] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const catalogById = useMemo(() => catalogMapFromItems(catalog), [catalog]);
  const selected = wishlists.find((row) => row._id === selectedId) || null;
  const picked = pickProductId ? catalogById.get(pickProductId) : undefined;
  const pickedIsClothing = picked?.category === "crew_clothing";

  const refresh = useCallback(async () => {
    if (!key) {
      setWishlists([]);
      setCatalog([]);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const [cat, lists] = await Promise.all([fetchChannel3Catalog(), fetchTreasurerWishlists(key)]);
      setCatalog(cat.items);
      setWishlists(lists.wishlists);
      setSelectedId((current) => current || lists.wishlists[0]?._id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [key]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!key || !title.trim() || !slug.trim()) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const row = await createTreasurerWishlist(key, { title: title.trim(), slug: slug.trim(), items: [] });
      setWishlists((prev) => [...prev, row]);
      setSelectedId(row._id);
      setTitle("");
      setSlug("");
      setNotice(t("wishlists.treasurer.created"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onAddItem = async () => {
    if (!key || !selectedId || !pickProductId) return;
    if (pickedIsClothing && !allowOptional) {
      setError(t("wishlists.treasurer.clothingNeedsOptional"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body: {
        channel3_product_id: string;
        quantity: number;
        target_amount_minor?: number;
        allow_optional: boolean;
      } = {
        channel3_product_id: pickProductId,
        quantity: Math.max(1, Number(quantity) || 1),
        allow_optional: Boolean(allowOptional),
      };
      const target = targetMinor.trim();
      if (target) body.target_amount_minor = Number(target);
      const updated = await addTreasurerWishlistItem(key, selectedId, body);
      setWishlists((prev) => prev.map((row) => (row._id === updated._id ? updated : row)));
      setNotice(t("wishlists.treasurer.itemAdded"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onRemove = async (productId: string) => {
    if (!key || !selectedId || !productId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await removeTreasurerWishlistItem(key, selectedId, productId);
      setWishlists((prev) => prev.map((row) => (row._id === updated._id ? updated : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onPublish = async (published: boolean) => {
    if (!key || !selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await publishTreasurerWishlist(key, selectedId, published);
      setWishlists((prev) => prev.map((row) => (row._id === updated._id ? updated : row)));
      setNotice(published ? t("wishlists.treasurer.published") : t("wishlists.treasurer.unpublished"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!key) {
    return (
      <section className="panel treasurer-wishlists" data-testid="treasurer-wishlists-panel">
        <h2>{t("wishlists.treasurer.heading")}</h2>
        <p className="hint">{t("wishlists.treasurer.needKey")}</p>
      </section>
    );
  }

  const lines = linesFromTreasurerItems(selected?.items, catalogById);

  return (
    <section className="panel treasurer-wishlists" data-testid="treasurer-wishlists-panel">
      <h2>{t("wishlists.treasurer.heading")}</h2>
      {error ? <p className="notice error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      <form className="stack-form" onSubmit={onCreate}>
        <h3>{t("wishlists.treasurer.create")}</h3>
        <label>
          {t("wishlists.treasurer.title")}
          <input value={title} onChange={(event) => setTitle(event.target.value)} data-testid="wishlist-create-title" />
        </label>
        <label>
          {t("wishlists.treasurer.slug")}
          <input value={slug} onChange={(event) => setSlug(event.target.value)} data-testid="wishlist-create-slug" />
        </label>
        <button type="submit" disabled={busy || !title.trim() || !slug.trim()} data-testid="wishlist-create-submit">
          {t("wishlists.treasurer.createSubmit")}
        </button>
      </form>
      <div className="wishlist-treasurer-lists">
        <label>
          {t("wishlists.treasurer.pickList")}
          <select
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            data-testid="wishlist-treasurer-select"
          >
            <option value="">{t("wishlists.treasurer.pickListEmpty")}</option>
            {wishlists.map((row) => (
              <option key={row._id} value={row._id}>
                {row.title} {row.published ? `(${t("wishlists.treasurer.badgePublished")})` : `(${t("wishlists.treasurer.badgeDraft")})`}
              </option>
            ))}
          </select>
        </label>
        {selected ? (
          <div className="wishlist-treasurer-selected" data-testid="wishlist-treasurer-selected">
            <p data-testid="wishlist-published-state">
              {selected.published ? t("wishlists.treasurer.badgePublished") : t("wishlists.treasurer.badgeDraft")}
            </p>
            <div className="wishlist-treasurer-actions">
              <button
                type="button"
                disabled={busy}
                onClick={() => void onPublish(true)}
                data-testid="wishlist-publish"
              >
                {t("wishlists.treasurer.publish")}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onPublish(false)}
                data-testid="wishlist-unpublish"
              >
                {t("wishlists.treasurer.unpublish")}
              </button>
            </div>
            <ul className="wishlist-treasurer-items">
              {lines.map((line) =>
                line.state === "unavailable" ? (
                  <li key={`missing-${line.channel3_product_id}`}>
                    <WishlistItemUnavailable productId={line.channel3_product_id} />
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void onRemove(line.channel3_product_id)}
                      data-testid={`wishlist-remove-${line.channel3_product_id}`}
                    >
                      {t("wishlists.treasurer.removeItem")}
                    </button>
                  </li>
                ) : (
                  <li key={line.item.channel3_product_id}>
                    <span data-testid="treasurer-wishlist-line">
                      {line.item.name} × {line.quantity}
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void onRemove(line.item.channel3_product_id)}
                      data-testid={`wishlist-remove-${line.item.channel3_product_id}`}
                    >
                      {t("wishlists.treasurer.removeItem")}
                    </button>
                  </li>
                ),
              )}
            </ul>
            <fieldset className="wishlist-add-item">
              <legend>{t("wishlists.treasurer.addItem")}</legend>
              <label>
                {t("wishlists.treasurer.catalogPick")}
                <select
                  value={pickProductId}
                  onChange={(event) => setPickProductId(event.target.value)}
                  data-testid="wishlist-catalog-pick"
                >
                  <option value="">{t("wishlists.treasurer.catalogPickEmpty")}</option>
                  {catalog.map((row) => (
                    <option key={row.channel3_product_id} value={row.channel3_product_id}>
                      {row.name}
                      {row.category === "crew_clothing" ? ` (${t("wishlists.treasurer.optionalCategory")})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("wishlists.treasurer.quantity")}
                <input
                  type="number"
                  min={1}
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                  data-testid="wishlist-add-quantity"
                />
              </label>
              <label>
                {t("wishlists.treasurer.targetMinor")}
                <input
                  value={targetMinor}
                  onChange={(event) => setTargetMinor(event.target.value)}
                  placeholder={t("wishlists.treasurer.targetMinorHint")}
                  data-testid="wishlist-add-target"
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={allowOptional}
                  onChange={(event) => setAllowOptional(event.target.checked)}
                  data-testid="wishlist-allow-optional"
                />
                {t("wishlists.treasurer.allowOptionalToggle")}
              </label>
              <button type="button" disabled={busy || !pickProductId} onClick={() => void onAddItem()} data-testid="wishlist-add-submit">
                {t("wishlists.treasurer.addSubmit")}
              </button>
            </fieldset>
          </div>
        ) : null}
      </div>
    </section>
  );
}

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
import { Channel3Thumb } from "../components/Channel3Thumb";
import { catalogMapFromItems, linesFromTreasurerItems } from "./catalogMap";
import { wishlistPublicHref } from "./wishlistAnchor";
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
  // True after the first successful load: "no wishlist yet" must not show before it, nor next to a load error.
  const [loaded, setLoaded] = useState(false);
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
      setLoaded(true);
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
        <h3>{t("wishlists.treasurer.heading")}</h3>
        <p className="hint">{t("wishlists.treasurer.needKey")}</p>
      </section>
    );
  }

  const lines = linesFromTreasurerItems(selected?.items, catalogById);

  return (
    <section className="panel treasurer-wishlists" data-testid="treasurer-wishlists-panel">
      <h3>{t("wishlists.treasurer.heading")}</h3>
      <p className="hint">{t("wishlists.treasurer.lead")}</p>
      {error ? <p className="notice error">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      <div className="wishlist-treasurer-lists">
        {!loaded ? (
          error ? null : (
            <p className="hint" aria-busy="true" data-testid="wishlist-treasurer-loading">
              {t("wishlists.treasurer.loading")}
            </p>
          )
        ) : wishlists.length === 0 ? (
          <p className="hint" data-testid="wishlist-treasurer-none">{t("wishlists.treasurer.noLists")}</p>
        ) : (
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
        )}
        {selected ? (
          <div className="wishlist-treasurer-selected" data-testid="wishlist-treasurer-selected">
            {/* What visitors see of this list, and the one action that changes it. */}
            <div className="wishlist-treasurer-state">
              <p data-testid="wishlist-published-state">
                <strong>{selected.published ? t("wishlists.treasurer.badgePublished") : t("wishlists.treasurer.badgeDraft")}</strong>
                {" · "}
                {selected.published ? t("wishlists.treasurer.publishedMeans") : t("wishlists.treasurer.draftMeans")}{" "}
                {selected.published ? (
                  <a href={wishlistPublicHref({ slug: selected.slug, id: selected._id })} target="_blank" rel="noopener noreferrer" data-testid="wishlist-public-link">
                    {t("wishlists.treasurer.openPublic")}
                  </a>
                ) : null}
              </p>
              <div className="wishlist-treasurer-actions">
                {selected.published ? (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => void onPublish(false)}
                    data-testid="wishlist-unpublish"
                  >
                    {t("wishlists.treasurer.unpublish")}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onPublish(true)}
                    data-testid="wishlist-publish"
                  >
                    {t("wishlists.treasurer.publish")}
                  </button>
                )}
              </div>
            </div>
            <h4>{t("wishlists.treasurer.itemsHeading", { count: lines.length })}</h4>
            {lines.length === 0 ? (
              <p className="hint" data-testid="wishlist-treasurer-no-items">{t("wishlists.treasurer.noItems")}</p>
            ) : null}
            <ul className="wishlist-treasurer-items">
              {lines.map((line) =>
                line.state === "unavailable" ? (
                  <li key={`missing-${line.channel3_product_id}`}>
                    <WishlistItemUnavailable productId={line.channel3_product_id} />
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => void onRemove(line.channel3_product_id)}
                      data-testid={`wishlist-remove-${line.channel3_product_id}`}
                    >
                      {t("wishlists.treasurer.removeItem")}
                    </button>
                  </li>
                ) : (
                  <li key={line.item.channel3_product_id}>
                    <Channel3Thumb src={line.item.image_url} title={line.item.name} size="sm" testId="treasurer-wishlist-photo" />
                    <span data-testid="treasurer-wishlist-line">
                      {line.item.name} × {line.quantity}
                    </span>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      aria-label={t("wishlists.treasurer.removeNamed", { name: line.item.name })}
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
                  onChange={(event) => {
                    const id = event.target.value;
                    setPickProductId(id);
                    // The catalogue knows how many the crew needs: 6 for a personal item, 1 for the boat.
                    const needed = Number(catalogById.get(id)?.quantity_needed);
                    if (Number.isInteger(needed) && needed > 0) setQuantity(String(needed));
                  }}
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
              <div className="wishlist-add-row">
                <label>
                  {t("wishlists.treasurer.quantity")}
                  <input
                    type="number"
                    min={1}
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    aria-describedby="wishlist-quantity-hint"
                    data-testid="wishlist-add-quantity"
                  />
                </label>
                <label>
                  {t("wishlists.treasurer.targetMinor")}
                  <input
                    inputMode="numeric"
                    value={targetMinor}
                    onChange={(event) => setTargetMinor(event.target.value)}
                    placeholder={t("wishlists.treasurer.targetMinorHint")}
                    data-testid="wishlist-add-target"
                  />
                </label>
              </div>
              <p className="hint" id="wishlist-quantity-hint">{t("wishlists.treasurer.quantityHint")}</p>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={allowOptional}
                  onChange={(event) => setAllowOptional(event.target.checked)}
                  data-testid="wishlist-allow-optional"
                />
                <span>{t("wishlists.treasurer.allowOptionalToggle")}</span>
              </label>
              <button type="button" disabled={busy || !pickProductId} onClick={() => void onAddItem()} data-testid="wishlist-add-submit">
                {t("wishlists.treasurer.addSubmit")}
              </button>
            </fieldset>
          </div>
        ) : null}
      </div>
      <form className="stack-form wishlist-create" onSubmit={onCreate}>
        <h4>{t("wishlists.treasurer.create")}</h4>
        <div className="wishlist-add-row">
          <label>
            {t("wishlists.treasurer.title")}
            <input value={title} onChange={(event) => setTitle(event.target.value)} data-testid="wishlist-create-title" />
          </label>
          <label>
            {t("wishlists.treasurer.slug")}
            <input value={slug} onChange={(event) => setSlug(event.target.value)} data-testid="wishlist-create-slug" />
          </label>
        </div>
        <button type="submit" className="secondary" disabled={busy || !title.trim() || !slug.trim()} data-testid="wishlist-create-submit">
          {t("wishlists.treasurer.createSubmit")}
        </button>
      </form>
    </section>
  );
}

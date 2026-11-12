import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchFeatures, fetchPublicWishlists } from "../api/escales";
import { notePayPalJsFeatures } from "../paypal/paypalJsVersion";
import type { PublicPledge, PublicWishlist } from "../api/types";
import { setLanguage } from "../i18n";
import { useTheme } from "../hooks/useTheme";
import { WishlistItemCard } from "./WishlistItemCard";
import { wishlistAnchor } from "./wishlistAnchor";
import "../styles/app.css";
import "./wishlists.css";

/** Placeholder cards shown while the first answer is on its way: two rows on a desktop. */
const SKELETON_CARDS = 8;

export function WishlistsPage() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [wishlists, setWishlists] = useState<PublicWishlist[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [contributor, setContributor] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const flags = await fetchFeatures().catch((err: unknown) => {
        notePayPalJsFeatures(null);
        throw err;
      });
      // Tells the PayPal buttons which browser SDK to use (v5 unless paypal_js_v6 is on).
      notePayPalJsFeatures(flags);
      const on = Boolean(flags.wishlists);
      setEnabled(on);
      if (!on) {
        setWishlists([]);
        return;
      }
      const body = await fetchPublicWishlists();
      setWishlists(body.wishlists);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setWishlists([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A link to one list (from the treasurer page) lands on it once the lists have loaded.
  useEffect(() => {
    if (loading || !wishlists.length) return;
    const anchor = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (!anchor) return;
    document.getElementById(anchor)?.scrollIntoView({ block: "start" });
  }, [loading, wishlists]);

  const onAuthorized = useCallback((_pledge: PublicPledge) => {
    void load();
  }, [load]);

  const lang = i18n.language?.startsWith("en") ? "en" : "fr";

  return (
    <div className="wishlists-shell" data-theme={theme} data-testid="wishlists-page">
      <header className="wishlists-header">
        <div>
          <h1>{t("wishlists.pageTitle")}</h1>
          <p className="hint">{t("wishlists.pageLead")}</p>
        </div>
        <div className="wishlists-controls">
          <a href="/" className="secondary" data-testid="wishlists-back-map">
            {t("wishlists.backToMap")}
          </a>
          <form
            className="wishlists-contributor"
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <label>
              {t("pledge.contributor")}
              <input
                value={contributor}
                onChange={(event) => setContributor(event.target.value)}
                data-testid="wishlists-contributor"
              />
            </label>
          </form>
          <div className="lang-switch" role="group" aria-label={t("app.language")}>
            <button
              type="button"
              className={lang === "fr" ? "active" : ""}
              onClick={() => setLanguage("fr")}
            >
              FR
            </button>
            <button
              type="button"
              className={lang === "en" ? "active" : ""}
              onClick={() => setLanguage("en")}
            >
              EN
            </button>
          </div>
          <button type="button" data-testid="wishlists-theme-toggle" onClick={() => toggleTheme()}>
            {theme === "light" ? t("app.themeDark") : t("app.themeLight")}
          </button>
        </div>
      </header>
      {loading ? <p role="status">{t("wishlists.loading")}</p> : null}
      {/* First load only: the shape of the cards to come, so the page is not an empty sheet.
          A reload after a pledge keeps the lists that are already on screen. */}
      {loading && wishlists.length === 0 ? (
        <div className="wishlist-grid" aria-hidden="true" data-testid="wishlists-skeleton">
          {Array.from({ length: SKELETON_CARDS }, (_unused, index) => (
            <div key={index} className="wishlist-item-card panel wishlist-skeleton">
              <span className="wishlist-skeleton-block wishlist-skeleton-image" />
              <span className="wishlist-skeleton-block wishlist-skeleton-title" />
              <span className="wishlist-skeleton-block wishlist-skeleton-line" />
              <span className="wishlist-skeleton-block wishlist-skeleton-bar" />
            </div>
          ))}
        </div>
      ) : null}
      {error ? <p className="notice error">{error}</p> : null}
      {enabled === false ? <p className="notice">{t("wishlists.disabled")}</p> : null}
      {!loading && enabled && wishlists.length === 0 ? <p>{t("wishlists.empty")}</p> : null}
      {wishlists.map((list) => (
        <section
          key={list.wishlist_id}
          id={wishlistAnchor({ slug: list.slug, id: list.wishlist_id })}
          className="wishlist-section"
          data-testid="wishlist-section"
        >
          <h2>{list.title}</h2>
          <div className="wishlist-grid">
            {(list.items || []).map((item) => (
              <WishlistItemCard
                key={`${list.wishlist_id}-${item.channel3_product_id}`}
                item={item}
                contributor={contributor}
                onAuthorized={onAuthorized}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

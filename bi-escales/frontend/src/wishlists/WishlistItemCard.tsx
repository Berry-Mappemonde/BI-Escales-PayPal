import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Channel3CatalogItem, PublicPledge } from "../api/types";
import { Channel3Thumb } from "../components/Channel3Thumb";
import { PledgeButton } from "../components/PledgeButton";
import { currencyUsesWholeUnits, parseWishlistPledgeAmount } from "./channel3Money";
import { formatMinorMoney, formatNativePrice, fundingPct } from "./channel3Format";
import { wishlistLineQuantity } from "./wishlistLine";
import { itemPresentmentCurrency, wishlistItemFundable, wishlistPledgeBody } from "./wishlistPledge";

export interface WishlistItemCardProps {
  item: Channel3CatalogItem;
  contributor?: string;
  onAuthorized?: (pledge: PublicPledge) => void;
}

export function WishlistItemCard({ item, contributor = "", onAuthorized }: WishlistItemCardProps) {
  const { t, i18n } = useTranslation();
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const currency = itemPresentmentCurrency(item);
  const defaultAmount = currencyUsesWholeUnits(currency) ? "1" : "1.00";
  const [amount, setAmount] = useState(defaultAmount);
  const [who, setWho] = useState(contributor);
  const pct = fundingPct(item);
  const priceLabel = formatNativePrice(item, lang);
  const qty = wishlistLineQuantity(item);
  const lineTarget = formatMinorMoney(item.target_amount_minor, item.target_currency || currency, lang);
  const buyUrl = String(item.channel3_buy_url || "").trim();
  const disclosure = String(item.channel3_buy_disclosure || "").trim();
  const showBuy = Boolean(item.fully_funded && buyUrl);
  const parsed = useMemo(() => parseWishlistPledgeAmount(amount, currency), [amount, currency]);
  const title = String(item.name || "").trim();
  const fundable = wishlistItemFundable(item);

  const pledgeValues = wishlistPledgeBody(item, {
    amountMajor: parsed.apiAmount || defaultAmount,
    description: t("wishlists.pledgeDescription", { title }),
    contributor: who.trim() || undefined,
    lang,
  });

  return (
    <article className="wishlist-item-card panel" data-testid="wishlist-item-card" data-currency={currency}>
      <Channel3Thumb src={item.image_url} title={title} size="lg" className="wishlist-item-image" testId="wishlist-item-image" />
      <h3 data-testid="wishlist-item-name">{title}</h3>
      <p className="wishlist-item-merchant" data-testid="wishlist-item-merchant">
        {item.merchant}
        {item.merchant_country ? ` · ${item.merchant_country}` : ""}
      </p>
      <p data-testid="wishlist-item-price">{priceLabel}</p>
      <p data-testid="wishlist-item-qty">{t("wishlists.quantityNeeded", { count: qty })}</p>
      {lineTarget ? (
        <p data-testid="wishlist-line-target" data-target-currency={item.target_currency || currency}>
          {t("wishlists.lineTarget", { amount: lineTarget })}
        </p>
      ) : null}
      {pct != null ? (
        <div className="gauge" data-testid="wishlist-funding-bar">
          <div className="gauge-track">
            <div className="gauge-fill tone-cap" style={{ width: `${pct}%` }} />
          </div>
          <p className="hint" data-testid="wishlist-funded-pct">
            {t("wishlists.fundedPctNative", {
              pct,
              funded: item.funded_display || "0",
              currency: item.funded_currency || currency,
              target: item.target_display || "—",
              targetCurrency: item.target_currency || currency,
            })}
          </p>
        </div>
      ) : null}
      {fundable ? (
        <div className="wishlist-fund-block" data-testid="wishlist-fund-block">
          <label>
            {t("wishlists.amountInCurrency", { currency })}
            <input
              data-testid="wishlist-fund-amount"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <label>
            {t("pledge.contributor")}
            <input
              data-testid="wishlist-fund-contributor"
              value={who}
              onChange={(event) => setWho(event.target.value)}
            />
          </label>
          <PledgeButton
            values={{ ...pledgeValues, currency: pledgeValues.currency }}
            disabled={parsed.kind !== "ok"}
            onAuthorized={onAuthorized}
          />
        </div>
      ) : null}
      {showBuy ? (
        <div className="wishlist-buy" data-testid="wishlist-buy-block">
          <p className="hint" data-testid="wishlist-buy-disclosure">
            {disclosure}
          </p>
          <a href={buyUrl} target="_blank" rel="noopener noreferrer" data-testid="wishlist-buy-link">
            {t("wishlists.buyViaChannel3")}
          </a>
        </div>
      ) : null}
    </article>
  );
}

export function WishlistItemUnavailable({ productId }: { productId: string }) {
  const { t } = useTranslation();
  return (
    <article className="wishlist-item-card panel unavailable" data-testid="wishlist-item-unavailable">
      <p>{t("wishlists.itemUnavailable", { productId })}</p>
    </article>
  );
}

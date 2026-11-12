import type { TFunction } from "i18next";
import type { FundView } from "../api/types";

function money(amount: number, currency: string, lang: string): string {
  return new Intl.NumberFormat(lang, { style: "currency", currency: currency || "EUR" }).format(amount);
}

/** The common fund's balance as money in the reader's language. */
export function formatCommonFundBalance(fund: FundView, lang: string): string {
  const balance = Number(fund.balance_eur);
  if (Number.isFinite(balance)) return money(balance, fund.currency, lang);
  return `${fund.balance_eur} ${fund.currency}`;
}

/** Amount fields that are not zero once anyone has given, even if the balance is back to zero. */
const ACTIVITY_FIELDS = ["income_eur", "captured_eur", "received_net_eur", "authorized_eur", "refunded_eur", "spending_eur"] as const;

/**
 * True only when every amount the server sent reads as zero. An amount it
 * cannot read counts as activity: the fund is never called empty on a guess.
 */
function nothingEverGiven(fund: FundView): boolean {
  return ACTIVITY_FIELDS.every((field) => {
    const value = fund[field];
    if (value === undefined || value === null || value === "") return true;
    const amount = Number(value);
    return Number.isFinite(amount) && amount === 0;
  });
}

/**
 * The public line for the common fund: an invitation while nobody has given,
 * otherwise its balance (and, at a zero balance, what was received and used).
 */
export function publicCommonFundMessage(fund: FundView, lang: string, t: TFunction): string {
  const balance = Number(fund.balance_eur);
  if (Number.isFinite(balance) && balance === 0) {
    if (nothingEverGiven(fund)) return t("fund.publicCommonEmpty");
    const received = Number(fund.received_net_eur ?? fund.income_eur);
    if (Number.isFinite(received) && received > 0) {
      return t("fund.publicCommonUsed", {
        balance: formatCommonFundBalance(fund, lang),
        received: money(received, fund.currency, lang),
      });
    }
  }
  return t("fund.publicCommon", { balance: formatCommonFundBalance(fund, lang) });
}

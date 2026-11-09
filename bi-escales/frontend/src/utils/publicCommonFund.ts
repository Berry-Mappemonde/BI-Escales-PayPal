import type { TFunction } from "i18next";
import type { FundView } from "../api/types";

export function formatCommonFundBalance(fund: FundView, lang: string): string {
  const balance = Number(fund.balance_eur);
  if (Number.isFinite(balance)) {
    return new Intl.NumberFormat(lang, {
      style: "currency",
      currency: fund.currency || "EUR",
    }).format(balance);
  }
  return `${fund.balance_eur} ${fund.currency}`;
}

export function publicCommonFundMessage(
  fund: FundView,
  lang: string,
  t: TFunction,
): string {
  const balance = Number(fund.balance_eur);
  if (Number.isFinite(balance) && balance === 0) {
    return t("fund.publicCommonEmpty");
  }
  return t("fund.publicCommon", { balance: formatCommonFundBalance(fund, lang) });
}

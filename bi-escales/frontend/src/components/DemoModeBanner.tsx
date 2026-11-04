import { useTranslation } from "react-i18next";

export function demoModeEnabled(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "1" || import.meta.env.VITE_PAYPAL_MOCK === "1";
}

export function DemoModeBanner() {
  const { t } = useTranslation();
  if (!demoModeEnabled()) return null;
  return (
    <div className="demo-banner" data-testid="demo-mode-banner" role="status">
      <strong>{t("demo.bannerTitle")}</strong>
      <span>{t("demo.bannerBody")}</span>
    </div>
  );
}

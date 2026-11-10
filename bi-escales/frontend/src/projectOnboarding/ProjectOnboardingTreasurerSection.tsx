import { useState } from "react";
import { useTranslation } from "react-i18next";
import { copyOnboardingLink, emailPreviewUrl } from "../api/projectOnboarding";

export function ProjectOnboardingTreasurerSection({
  adminKey,
  projectId,
}: {
  adminKey: string;
  projectId: string;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language.toLowerCase().startsWith("en") ? "en" : "fr";
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onCopy = async () => {
    setError(null);
    try {
      const link = await copyOnboardingLink(projectId, adminKey);
      await navigator.clipboard.writeText(link);
      setCopied(link);
    } catch {
      setError(t("projectOnboarding.copyError"));
    }
  };

  return (
    <section data-testid="treasurer-onboarding-tools" className="treasurer-onboarding-tools">
      <h3>{t("projectOnboarding.treasurerHeading")}</h3>
      <p>
        <a href={emailPreviewUrl(projectId, lang)} target="_blank" rel="noreferrer">
          {t("projectOnboarding.emailPreview")}
        </a>
      </p>
      <button type="button" onClick={() => void onCopy()} disabled={!adminKey.trim()}>
        {t("projectOnboarding.copyOnboardingLink")}
      </button>
      {copied ? <p className="notice ok">{t("projectOnboarding.copied")}</p> : null}
      {error ? <p className="notice warn">{error}</p> : null}
    </section>
  );
}

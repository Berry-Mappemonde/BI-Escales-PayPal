import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchProjectOnboarding } from "../api/projectOnboarding";

export function ProjectOnboardingReturnPage({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language.toLowerCase().startsWith("en") ? "en" : "fr";
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const qs = new URLSearchParams({
      merchantIdInPayPal: params.get("merchantIdInPayPal") || params.get("merchantId") || "",
      permissionsGranted: params.get("permissionsGranted") || "",
      isEmailConfirmed: params.get("isEmailConfirmed") || "",
    });
    const path = `/api/escales/project-onboarding/projects/${encodeURIComponent(projectId)}/onboarding/return?${qs}`;
    const base = (import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
    const url = base ? `${base}${path}` : path;
    void fetch(url)
      .then((res) => (res.ok ? res.json() : null))
      .then(() => fetchProjectOnboarding(projectId, lang))
      .then((view) => setStatus(view?.onboarding_status || "pending"))
      .catch(() => setStatus("error"));
  }, [projectId, lang]);

  return (
    <main data-testid="project-onboarding-return">
      <h1>{t("projectOnboarding.returnTitle")}</h1>
      {status ? <p>{t(`projectOnboarding.projectStatus.${status}`, { defaultValue: status })}</p> : <p>{t("projectOnboarding.loading")}</p>}
      <p>
        <a href={`/projects/${encodeURIComponent(projectId)}/onboarding`}>{t("projectOnboarding.backToProject")}</a>
      </p>
    </main>
  );
}

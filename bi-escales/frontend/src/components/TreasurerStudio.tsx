import { useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { enableStudioDevValidations } from "ag-studio";
import type { PublicPledge } from "../api/types";
import { agGridLicenseKey, agStudioLlmEndpoint } from "../config/features";
import { escalesStudioTheme } from "../studio/escalesTheme";
import { treasurerInitialState } from "../studio/initialReport";
import { pledgeStudioData } from "../studio/pledgeData";
import { AgStudioAiModule, createTreasurerHarness } from "../studio/treasurerAgent";
import { escalesWidgets } from "../studio/widgets";
import "../studio/studio.css";

if (import.meta.env.DEV) {
  enableStudioDevValidations();
}

export default function TreasurerStudio({
  pledges,
  onClose,
}: {
  pledges: PublicPledge[];
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const data = useMemo(() => pledgeStudioData(pledges, language), [pledges, language]);
  const initialState = useMemo(() => treasurerInitialState(language), [language]);
  const widgets = useMemo(() => (config: Parameters<typeof escalesWidgets>[0]) => escalesWidgets(config, language), [language]);
  const licenseKey = agGridLicenseKey();
  const ai = useMemo(() => createTreasurerHarness(agStudioLlmEndpoint(), language), [language]);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // The treasurer panel lives in a 340px sidebar, too narrow for this report.
  return createPortal(
    <div className="studio-overlay" role="dialog" aria-modal="true" aria-label={t("studio.heading")}>
      <header className="studio-overlay-header">
        <h2>{t("studio.heading")}</h2>
        <button ref={closeRef} type="button" data-testid="treasurer-studio-close" onClick={onClose}>
          {t("studio.close")}
        </button>
      </header>
      <div
        className="ag-theme-mode treasurer-studio"
        data-ag-theme-mode="escales-night"
        data-testid="treasurer-ag-studio"
      >
        <AgStudioProvider licenseKey={licenseKey} modules={[AgStudioAiModule]}>
          <AgStudio
            style={{ height: "100%", width: "100%" }}
            className="escales-studio"
            theme={escalesStudioTheme}
            data={data}
            initialState={initialState}
            widgets={widgets}
            ai={ai}
            mode="edit"
          />
        </AgStudioProvider>
      </div>
    </div>,
    document.body,
  );
}

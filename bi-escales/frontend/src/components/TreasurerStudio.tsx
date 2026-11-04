import { useMemo } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { enableStudioDevValidations } from "ag-studio";
import type { PublicPledge } from "../api/types";
import { agGridLicenseKey, agStudioLlmEndpoint } from "../config/features";
import { escalesStudioTheme } from "../studio/escalesTheme";
import { treasurerInitialState } from "../studio/initialReport";
import { pledgeStudioData } from "../studio/pledgeData";
import { AgStudioAiModule, createTreasurerHarness } from "../studio/treasurerAgent";
import { escalesWidgets } from "../studio/widgets";

if (import.meta.env.DEV) {
  enableStudioDevValidations();
}

export default function TreasurerStudio({ pledges }: { pledges: PublicPledge[] }) {
  const data = useMemo(() => pledgeStudioData(pledges), [pledges]);
  const initialState = useMemo(() => treasurerInitialState(), []);
  const licenseKey = agGridLicenseKey();
  const ai = useMemo(() => createTreasurerHarness(agStudioLlmEndpoint()), []);

  return (
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
          widgets={escalesWidgets}
          ai={ai}
          mode="edit"
        />
      </AgStudioProvider>
    </div>
  );
}

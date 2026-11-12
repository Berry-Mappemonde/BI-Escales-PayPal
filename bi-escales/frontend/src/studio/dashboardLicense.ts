import { LicenseManager } from "ag-grid-enterprise";
import { AgStudioLicenseManager } from "ag-studio";

export function dashboardCapabilities(key: string) {
  const studio = AgStudioLicenseManager.getLicenseDetails(key, new Set(["CORE"]));
  const agent = AgStudioLicenseManager.getLicenseDetails(key, new Set(["PRO-AI"]));
  const grid = LicenseManager.getLicenseDetails(key);
  const active = (license: { valid: boolean; expired?: boolean; trialExpired?: boolean; incorrectLicenseType?: boolean }) =>
    license.valid && !license.expired && !license.trialExpired && !license.incorrectLicenseType;

  return {
    charts: active(grid) && grid.suppliedLicenseType === "BOTH",
    studio: active(studio),
    agent: active(agent),
  };
}

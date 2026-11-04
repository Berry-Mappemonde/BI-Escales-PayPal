/**
 * Hôte de la fiche. Dérivé de naviguide-escales/src/components/EscalePopup.jsx
 * (le contenu React EscalePopup). Le popup Leaflet film / followPopup n'est pas repris.
 */
import { EscaleSheet } from "./EscaleSheet.jsx";

export function EscalePopup({ stop, fiche, loading, error, onClose, pledge, onPledgeAuthorized, fund, fundError, adminKey }) {
  if (!stop) return null;
  return (
    <div data-testid="escale-popup" className="escale-popup-card">
      <EscaleSheet
        stop={stop}
        fiche={fiche}
        loading={loading}
        error={error}
        onClose={onClose}
        pledge={pledge}
        onPledgeAuthorized={onPledgeAuthorized}
        fund={fund}
        fundError={fundError}
        adminKey={adminKey}
      />
    </div>
  );
}

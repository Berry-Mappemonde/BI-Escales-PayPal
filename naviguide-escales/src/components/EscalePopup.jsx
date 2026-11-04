import { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { unmountRootLater } from "../utils/unmountRootLater.js";
import { LangProvider } from "../i18n/LangContext.jsx";
import { followPopupToMarker } from "./eventBubble.js";
import { EscaleSheet } from "./EscaleSheet.jsx";
import {
  ESCALE_POPUP_MAX_HEIGHT,
  ESCALE_POPUP_MAX_WIDTH,
  createEscalePopupOptions,
  ensureEscalePopup,
  findParkedBoatMarker,
  findWaypointMarker,
  handleWaypointMarkerClick,
  isEscaleCloseClick,
  requestEscaleClose,
  shouldCloseEscaleSheet,
} from "./escalePopup.js";

export {
  ESCALE_POPUP_MAX_HEIGHT,
  ESCALE_POPUP_MAX_WIDTH,
  createEscalePopupOptions,
  ensureEscalePopup,
  findParkedBoatMarker,
  findWaypointMarker,
  handleWaypointMarkerClick,
  isEscaleCloseClick,
  requestEscaleClose,
  shouldCloseEscaleSheet,
};

/** Contenu React de la fiche ancrée au drapeau. */
export function EscalePopup({ stop, fiche, loading, error, onClose, onFocus }) {
  if (!stop) return null;
  return (
    <div
      data-testid="escale-popup"
      className="escale-popup-card"
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      style={{
        width: "100%",
        maxWidth: ESCALE_POPUP_MAX_WIDTH,
        maxHeight: ESCALE_POPUP_MAX_HEIGHT,
        overflowY: "auto",
      }}
    >
      <EscaleSheet
        stop={stop}
        fiche={fiche}
        loading={loading}
        error={error}
        onClose={onClose}
        onFocus={onFocus}
      />
    </div>
  );
}

function renderSheet(root, host, sheet) {
  if (!host || !root) return;
  root.render(sheet?.stop ? (
    <LangProvider>
      <EscalePopup
        stop={sheet.stop}
        fiche={sheet.fiche}
        loading={sheet.loading}
        error={sheet.error}
        onClose={sheet.onClose}
        onFocus={sheet.onFocus}
      />
    </LangProvider>
  ) : null);
}

/**
 * Un seul `L.popup` ancré au drapeau de l'escale ouverte (motif EventBubble).
 * Croix, Échap, ou un autre drapeau ferment / remplacent.
 */
export function attachEscalePopup(scene, L) {
  const popup = ensureEscalePopup(null, L);
  popup._biFitting = true;
  const canDom = typeof document !== "undefined";
  const host = canDom ? document.createElement("div") : { nodeType: 1 };
  let root = null;
  if (canDom) {
    try { root = createRoot(host); } catch { root = null; }
  }
  let open = false;
  let sheet = null;

  const win = typeof window !== "undefined" ? window : null;

  function markerOf() {
    return findWaypointMarker(scene, sheet?.stop);
  }

  function follow() {
    return followPopupToMarker(popup, markerOf());
  }

  function hide() {
    if (!open && !popup._map) {
      renderSheet(root, host, null);
      return;
    }
    try { popup.remove(); } catch { /* déjà retiré */ }
    open = false;
    renderSheet(root, host, null);
  }

  function requestClose() {
    requestEscaleClose(sheet);
    // Retirer après le clic : sinon le même geste retombe sur le drapeau.
    if (typeof window !== "undefined" && typeof window.setTimeout === "function") {
      window.setTimeout(() => hide(), 0);
    } else {
      hide();
    }
  }

  function show() {
    if (!sheet?.stop) {
      hide();
      return;
    }
    const marker = markerOf();
    if (!marker) return;
    renderSheet(root, host, sheet);
    popup.setContent(host);
    popup.setLatLng(marker.getLatLng());
    const filmOn = Boolean(scene.config?.filmActive);
    if (!filmOn) {
      try { scene.callbacks?.onManualNavigation?.(); } catch { /* tests */ }
    }
    if (!open) {
      try { popup.openOn(scene.map); } catch { /* carte absente (tests) */ }
      open = true;
    }
    follow();
    if (filmOn) return;
    try {
      const ll = marker.getLatLng();
      const zoom = scene.map?.getZoom?.();
      scene.map?.setView?.(ll, Number.isFinite(zoom) ? Math.max(zoom, 6) : 6, { animate: false });
    } catch { /* carte absente (tests) */ }
  }

  function setSheet(next) {
    sheet = next?.stop ? next : null;
    if (!sheet) {
      hide();
      return;
    }
    show();
  }

  function onEsc(event) {
    if (event.key !== "Escape" && event.key !== "Esc") return;
    if (!open) return;
    event.stopPropagation();
    event.preventDefault();
    requestClose();
  }

  function onHostClick(event) {
    if (!isEscaleCloseClick(event)) return;
    event.preventDefault();
    event.stopPropagation();
    requestClose();
  }

  host.addEventListener?.("click", onHostClick);
  win?.addEventListener("keydown", onEsc, true);

  const api = {
    popup,
    follow,
    sync() {
      if (!sheet?.stop) {
        if (open) hide();
        return;
      }
      if (markerOf()) show();
    },
    setSheet,
    hide,
    dispose() {
      host.removeEventListener?.("click", onHostClick);
      win?.removeEventListener("keydown", onEsc, true);
      hide();
      // Différé : dispose() part souvent d'un nettoyage d'effet React ; un
      // unmount synchrone pendant le rendu déclenche l'erreur « synchronously unmount ».
      unmountRootLater(root);
    },
  };
  scene.escalePopup = api;
  if (win?.__naviguideEscaleSheet) api.setSheet(win.__naviguideEscaleSheet);
  return api;
}

/** Pousse l'état React dans le `L.popup` de la scène. */
export function EscalePopupHost({ stop, fiche, loading, error, onClose, onFocus }) {
  useEffect(() => {
    const payload = stop ? { stop, fiche, loading, error, onClose, onFocus } : null;
    if (typeof window !== "undefined") window.__naviguideEscaleSheet = payload;
    const apply = () => {
      const scene = typeof window !== "undefined" ? window.__naviguideScene : null;
      if (!scene?.escalePopup) return false;
      scene.escalePopup.setSheet(payload);
      return true;
    };
    if (apply()) return undefined;
    const id = setInterval(() => {
      if (apply()) clearInterval(id);
    }, 80);
    return () => clearInterval(id);
  }, [stop, fiche, loading, error, onClose, onFocus]);
  return null;
}

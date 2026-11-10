/** Keyboard activation for Leaflet stop divIcons (Enter / Space). */
const boundStopControls = new WeakSet();

function attachStopMarkerKeyboard(marker, stop, onActivate) {
  const root = marker.getElement?.();
  const control = root?.querySelector?.("[data-stop-marker]");
  if (!control || typeof onActivate !== "function" || boundStopControls.has(control)) return;
  boundStopControls.add(control);
  control.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    event.stopPropagation();
    const target = marker.options?.stopData || stop;
    onActivate(target);
  });
}

export function bindStopMarkerKeyboard(marker, stop, onActivate) {
  attachStopMarkerKeyboard(marker, stop, onActivate);
  marker.on("add", () => attachStopMarkerKeyboard(marker, stop, onActivate));
}

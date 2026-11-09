/** Keyboard activation for Leaflet stop divIcons (Enter / Space). */
export function bindStopMarkerKeyboard(marker, stop, onActivate) {
  marker.on("add", () => {
    const root = marker.getElement?.();
    const control = root?.querySelector?.("[data-stop-marker]");
    if (!control || typeof onActivate !== "function") return;
    control.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      const target = marker.options?.stopData || stop;
      onActivate(target);
    });
  });
}

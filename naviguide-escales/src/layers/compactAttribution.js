/**
 * Compact map credits, after MapLibre's compact attribution: when the visible
 * map (map width minus the open panels) is narrower than
 * COMPACT_ATTRIBUTION_BELOW_PX, the credit bar folds into an "ⓘ" button in the
 * bottom-right corner of the visible map. A tap opens every credit in a
 * popover above the panels; a second tap, the close button or Escape folds it.
 */

export const COMPACT_ATTRIBUTION_BELOW_PX = 260;

/** Narrowest popover that keeps the credits readable (px). */
export const COMPACT_POPOVER_MIN_PX = 300;

export function isCompactAttribution(visibleWidth) {
  return Number.isFinite(visibleWidth) && visibleWidth < COMPACT_ATTRIBUTION_BELOW_PX;
}

/**
 * Fixed-position box for the open credits: right-aligned on the button when
 * there is room, otherwise widened toward the right, always inside the
 * viewport with `margin` on each side.
 */
export function popoverPlacement(buttonRect, viewportWidth, viewportHeight, margin = 8) {
  const vw = Math.max(0, Number(viewportWidth) || 0);
  const vh = Math.max(0, Number(viewportHeight) || 0);
  const minWidth = Math.min(COMPACT_POPOVER_MIN_PX, Math.max(0, vw - 2 * margin));
  let right = Math.max(margin, Math.round(vw - Number(buttonRect?.right ?? vw)));
  if (vw - right - margin < minWidth) right = Math.max(margin, Math.round(vw - margin - minWidth));
  const bottom = Math.max(margin, Math.round(vh - Number(buttonRect?.top ?? vh) + 4));
  return {
    right,
    bottom,
    maxWidth: Math.max(0, Math.round(vw - right - margin)),
    maxHeight: Math.max(0, Math.round(vh - bottom - margin)),
  };
}

function stopMapEvents(el) {
  for (const type of ["click", "dblclick", "mousedown", "pointerdown", "touchstart", "wheel"]) {
    el.addEventListener(type, (event) => event.stopPropagation());
  }
}

/** Adds the compact mode to a Leaflet map's attribution control. Returns a cleanup. */
export function installCompactAttribution(map, { doc = globalThis.document, win = globalThis.window } = {}) {
  const control = map?.attributionControl;
  const corner = map?._controlCorners?.bottomright;
  if (!control || !corner || !doc || !win || typeof control.getContainer !== "function") return () => {};
  const credits = control.getContainer();
  const mapEl = map.getContainer();

  const button = doc.createElement("button");
  button.type = "button";
  button.className = "naviguide-attrib-toggle";
  button.setAttribute("data-testid", "attribution-toggle");
  button.setAttribute("aria-label", "Crédits de la carte · Map credits");
  button.setAttribute("aria-expanded", "false");
  button.textContent = "ⓘ";
  stopMapEvents(button);
  corner.appendChild(button);

  const popover = doc.createElement("div");
  popover.className = "naviguide-attrib-popover";
  popover.setAttribute("data-testid", "attribution-popover");
  popover.setAttribute("role", "dialog");
  popover.setAttribute("aria-label", "Crédits de la carte · Map credits");
  popover.hidden = true;
  const text = doc.createElement("div");
  text.className = "naviguide-attrib-popover-text";
  text.setAttribute("data-testid", "attribution-popover-text");
  const close = doc.createElement("button");
  close.type = "button";
  close.className = "naviguide-attrib-popover-close";
  close.setAttribute("data-testid", "attribution-close");
  close.setAttribute("aria-label", "Fermer · Close");
  close.textContent = "×";
  popover.append(text, close);
  doc.body.appendChild(popover);

  let compact = false;
  let open = false;
  const place = () => {
    const box = popoverPlacement(button.getBoundingClientRect(), win.innerWidth, win.innerHeight);
    popover.style.right = `${box.right}px`;
    popover.style.bottom = `${box.bottom}px`;
    popover.style.maxWidth = `${box.maxWidth}px`;
    popover.style.maxHeight = `${box.maxHeight}px`;
  };
  const setOpen = (value) => {
    open = Boolean(value) && compact;
    popover.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) {
      text.innerHTML = credits.innerHTML;
      place();
    }
  };
  const measure = () => {
    const next = isCompactAttribution(corner.getBoundingClientRect().width);
    if (next !== compact) {
      compact = next;
      mapEl.classList.toggle("naviguide-attrib-compact", compact);
      if (!compact) setOpen(false);
    }
    if (open) place();
  };

  button.addEventListener("click", () => setOpen(!open));
  close.addEventListener("click", () => setOpen(false));
  const onKey = (event) => { if (event.key === "Escape") setOpen(false); };
  doc.addEventListener("keydown", onKey);
  win.addEventListener("resize", measure);
  const resizeObserver = typeof win.ResizeObserver === "function" ? new win.ResizeObserver(measure) : null;
  resizeObserver?.observe(corner);
  corner.addEventListener("transitionend", measure);
  const mutationObserver = typeof win.MutationObserver === "function"
    ? new win.MutationObserver(() => { if (open) text.innerHTML = credits.innerHTML; })
    : null;
  mutationObserver?.observe(credits, { childList: true, subtree: true, characterData: true });
  measure();

  return () => {
    resizeObserver?.disconnect();
    mutationObserver?.disconnect();
    doc.removeEventListener("keydown", onKey);
    win.removeEventListener("resize", measure);
    corner.removeEventListener("transitionend", measure);
    mapEl.classList.remove("naviguide-attrib-compact");
    button.remove();
    popover.remove();
  };
}

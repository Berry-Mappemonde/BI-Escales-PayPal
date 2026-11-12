/**
 * How the Web SDK v6 buttons and card fields look, so that the v6 path matches
 * today's v5 checkout. Appearance only: nothing here starts, creates or approves
 * a payment.
 *
 * v5 takes a `style` object (`color`, `height`, `layout`, ...). v6 has no such
 * object: `<paypal-button>` takes a colour class and is sized with ordinary CSS
 * on the element, and card fields take a small CSS-like object per field. The
 * facts below were read from the sandbox v6 component itself (11 Nov 2026):
 *
 *  - colour classes: `paypal-gold` (default), `paypal-blue`, `paypal-white`
 *    (white, grey border) and `paypal-black`. There is no silver;
 *  - the element is `inline-block`, 225 x 45 px with a `type`, and its inner
 *    button fills whatever width and height the element is given;
 *  - there is no tagline, and the logo and label sit on one line.
 */
import type { MerchantStyleObject } from "@paypal/paypal-js/sdk-v6";

/** The part of a v5 `style` object the v6 path can honour. */
export type V5ButtonStyle = {
  label?: string;
  color?: string;
  height?: number;
  layout?: string;
  shape?: string;
  tagline?: boolean;
};

export type V6ButtonColorClass = "paypal-gold" | "paypal-blue" | "paypal-white" | "paypal-black";

const COLOR_CLASSES: Record<string, V6ButtonColorClass> = {
  gold: "paypal-gold",
  blue: "paypal-blue",
  white: "paypal-white",
  black: "paypal-black",
  // v6 has no silver button. White is its light, quiet one: the closest to v5's silver.
  silver: "paypal-white",
};

/** The v6 colour class for a v5 `style.color`. Unknown or missing: gold, PayPal's default in both SDKs. */
export function v6ButtonColorClass(color: unknown): V6ButtonColorClass {
  return COLOR_CLASSES[String(color ?? "").trim().toLowerCase()] ?? "paypal-gold";
}

/** PayPal's own limits for a button height (v5 `style.height`), kept for v6. */
const MIN_BUTTON_HEIGHT = 25;
const MAX_BUTTON_HEIGHT = 55;

/**
 * Gives a v6 button element the look its v5 `style` asked for:
 *  - the colour class;
 *  - the full width of its container, as v5 Smart Buttons take (the v6 element
 *    is 225 px wide unless told otherwise);
 *  - the height, when the style names one inside PayPal's limits; otherwise
 *    the element keeps PayPal's own 45 px.
 */
export function applyV6ButtonLook(element: HTMLElement, style?: V5ButtonStyle): void {
  element.classList.remove("paypal-gold", "paypal-blue", "paypal-white", "paypal-black");
  element.classList.add(v6ButtonColorClass(style?.color));
  // block, not the element's own inline-block: no line box, so no stray gap under it.
  element.style.display = "block";
  element.style.width = "100%";
  const height = Number(style?.height);
  if (Number.isFinite(height) && height >= MIN_BUTTON_HEIGHT && height <= MAX_BUTTON_HEIGHT) {
    element.style.height = `${height}px`;
  }
}

/** Space between two stacked PayPal buttons (PayPal, then Pay Later), as in v5's vertical layout. */
export const STACKED_BUTTON_GAP_PX = 8;

type Palette = { fg: string; field: string; line: string; placeholder: string; accent: string; danger: string };

/** The shell's own colours (styles/tokens.css), used when the page's tokens cannot be read. */
const FALLBACK: Record<"dark" | "light", Palette> = {
  dark: { fg: "#ededed", field: "#1f1f1f", line: "#333333", placeholder: "#8f8f8f", accent: "#4f8cff", danger: "#eb5a5a" },
  light: { fg: "#171717", field: "#f7f7f6", line: "#cfcfcc", placeholder: "#6b6b6b", accent: "#2563d9", danger: "#c9302c" },
};

function shellTheme(): "dark" | "light" {
  return typeof document !== "undefined" && document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function shellPalette(): Palette {
  const fallback = FALLBACK[shellTheme()];
  if (typeof document === "undefined" || typeof getComputedStyle !== "function") return fallback;
  const styles = getComputedStyle(document.documentElement);
  // Plain colours only: the fields live in PayPal's iframe, where our variables mean nothing.
  const read = (name: string, otherwise: string) => {
    const value = styles.getPropertyValue(name).trim();
    return /^#[0-9a-f]{3,8}$/i.test(value) || /^rgba?\([\d\s.,%/]+\)$/i.test(value) ? value : otherwise;
  };
  return {
    fg: read("--color-fg", fallback.fg),
    field: read("--color-raised", fallback.field),
    line: read("--color-line-strong", fallback.line),
    placeholder: read("--color-fg-3", fallback.placeholder),
    accent: read("--color-accent", fallback.accent),
    danger: read("--color-danger", fallback.danger),
  };
}

/**
 * The style for one v6 card field, in the shell's current theme. v6 accepts a
 * fixed list of selectors and properties (see MerchantStyleObject); this uses
 * only those. Read when the field is created: v6 has no call to restyle a
 * field that is already on the page, so a theme switch shows on the next mount.
 */
export function v6CardFieldStyle(): MerchantStyleObject {
  const { fg, field, line, placeholder, accent, danger } = shellPalette();
  return {
    input: {
      background: field,
      color: fg,
      border: `1px solid ${line}`,
      borderRadius: "6px",
      // 16px: a smaller input makes iOS Safari zoom the page on focus.
      fontSize: "16px",
      fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
      padding: "10px 12px",
      boxShadow: "none",
      outline: "none",
    },
    "input::placeholder": { color: placeholder },
    "input.focus": { border: `1px solid ${accent}`, boxShadow: "none", outline: "none" },
    "input.invalid": { color: danger, border: `1px solid ${danger}` },
    ".invalid": { color: danger },
    label: { color: placeholder },
  };
}

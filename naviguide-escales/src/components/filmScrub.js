/** Keyboard navigation for the film scrub bar. */
export function scrubKeyTarget(key, shiftKey, barNm, barTotal) {
  const total = Number(barTotal);
  if (!(total > 0)) return null;
  const at = Math.max(0, Math.min(total, Number(barNm) || 0));
  const step = total * (shiftKey ? 0.1 : 0.01);
  let target;
  switch (key) {
    case "ArrowLeft":
    case "ArrowDown":
      target = at - step;
      break;
    case "ArrowRight":
    case "ArrowUp":
      target = at + step;
      break;
    case "PageDown":
      target = at - total * 0.1;
      break;
    case "PageUp":
      target = at + total * 0.1;
      break;
    case "Home":
      target = 0;
      break;
    case "End":
      target = total;
      break;
    default:
      return null;
  }
  return Math.max(0, Math.min(total, target));
}

/** Trusted keyboard-generated clicks have detail === 0 and no pointer position. */
export function isKeyboardClick(e) {
  return e?.isTrusted === true && Number(e?.detail) === 0;
}

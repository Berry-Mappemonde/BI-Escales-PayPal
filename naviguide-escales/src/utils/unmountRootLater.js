/**
 * Démonte une racine React hors du cycle de rendu en cours.
 * Appeler `root.unmount()` depuis un nettoyage d'effet provoque l'erreur
 * « Attempted to synchronously unmount a root while React was already rendering ».
 */
export function unmountRootLater(root, schedule) {
  if (!root || typeof root.unmount !== "function") return;
  const run = () => {
    try { root.unmount(); } catch { /* déjà démontée */ }
  };
  const later = schedule || (typeof setTimeout === "function" ? (fn) => setTimeout(fn, 0) : null);
  if (later) later(run);
  else run();
}

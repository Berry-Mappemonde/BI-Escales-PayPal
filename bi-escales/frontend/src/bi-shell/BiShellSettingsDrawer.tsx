import type { ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children?: ReactNode;
};

export function BiShellSettingsDrawer({ open, title, onClose, children }: Props) {
  return (
    <aside
      className="bi-shell-settings"
      data-testid="bi-shell-settings"
      hidden={!open}
      aria-hidden={!open}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <strong>{title}</strong>
        <button type="button" className="bi-nav-icon" data-testid="bi-shell-settings-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <section className="bi-slot" data-slot="settings.body" data-testid="bi-slot-settings">
        <p className="bi-slot-label">settings</p>
        {children ?? <p className="bi-slot-empty">Empty — theme, language mirrors, demo flags, clock helpers</p>}
      </section>
    </aside>
  );
}

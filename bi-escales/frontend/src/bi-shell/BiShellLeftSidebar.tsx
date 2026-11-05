import type { ReactNode } from "react";

function Slot({ id, label, children }: { id: string; label: string; children?: ReactNode }) {
  return (
    <section className="bi-slot" data-slot={id} data-testid={`bi-slot-${id}`}>
      <p className="bi-slot-label">{label}</p>
      {children ?? <p className="bi-slot-empty">Empty — Escalés feature mounts here</p>}
    </section>
  );
}

type Props = {
  open: boolean;
  labels: {
    marinas: string;
    projects: string;
    stopovers: string;
    captain: string;
    membership: string;
  };
  marinas?: ReactNode;
  projects?: ReactNode;
  stopovers?: ReactNode;
  captain?: ReactNode;
  membership?: ReactNode;
};

export function BiShellLeftSidebar({
  open,
  labels,
  marinas,
  projects,
  stopovers,
  captain,
  membership,
}: Props) {
  return (
    <aside
      className={`bi-shell-left${open ? "" : " is-collapsed"}`}
      data-testid="bi-shell-left"
      aria-hidden={!open}
    >
      <Slot id="left.marinas" label={labels.marinas}>
        {marinas}
      </Slot>
      <Slot id="left.projects" label={labels.projects}>
        {projects}
      </Slot>
      <Slot id="left.stopovers" label={labels.stopovers}>
        {stopovers}
      </Slot>
      <Slot id="left.captain" label={labels.captain}>
        {captain}
      </Slot>
      <Slot id="left.membership" label={labels.membership}>
        {membership}
      </Slot>
    </aside>
  );
}

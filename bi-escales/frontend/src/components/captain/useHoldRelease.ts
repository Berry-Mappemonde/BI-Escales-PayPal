import { useCallback, useEffect, useRef, useState } from "react";
import { voidPledge } from "../../api/escales";
import type { PublicPledge } from "../../api/types";
import { sumEur } from "./captainEvidence";

/** How long a release can still be undone. Nothing reaches PayPal before it ends. */
export const UNDO_WINDOW_SECONDS = 5;

export interface HoldRelease {
  phase: "counting" | "sending" | "done" | "cancelled";
  secondsLeft: number;
  releasedCount: number;
  releasedEur: number;
  failed: { pledge: PublicPledge; message: string }[];
}

interface Options {
  adminKey: string;
  missingKeyMessage: string;
  onUpdated: (pledge: PublicPledge) => void;
}

/**
 * The undo window for releasing a milestone's holds. It lives above the card
 * because each void removes a pledge from the queue, which would otherwise
 * unmount the card and lose the result.
 *
 * Leaving cancels: closing the drawer unmounts this hook, and hiding the page
 * stops the countdown, so a void is never sent while Undo cannot be seen.
 */
export function useHoldRelease({ adminKey, missingKeyMessage, onUpdated }: Options) {
  const [releases, setReleases] = useState<Record<string, HoldRelease>>({});
  const timers = useRef(new Map<string, ReturnType<typeof setInterval>>());
  const sending = useRef(new Set<string>());
  const latest = useRef({ adminKey, missingKeyMessage, onUpdated });

  useEffect(() => {
    latest.current = { adminKey, missingKeyMessage, onUpdated };
  });

  const patch = useCallback((milestoneId: string, change: (row: HoldRelease) => HoldRelease) => {
    setReleases((all) => (all[milestoneId] ? { ...all, [milestoneId]: change(all[milestoneId]) } : all));
  }, []);

  const stopTimer = useCallback((milestoneId: string) => {
    const timer = timers.current.get(milestoneId);
    if (timer !== undefined) clearInterval(timer);
    timers.current.delete(milestoneId);
  }, []);

  const send = useCallback(
    async (milestoneId: string, targets: PublicPledge[]) => {
      sending.current.add(milestoneId);
      patch(milestoneId, (row) => ({ ...row, phase: "sending", failed: [] }));
      const released: PublicPledge[] = [];
      const failed: HoldRelease["failed"] = [];
      for (const pledge of targets) {
        const key = latest.current.adminKey.trim();
        if (!key) {
          failed.push({ pledge, message: latest.current.missingKeyMessage });
          continue;
        }
        try {
          latest.current.onUpdated(await voidPledge(pledge.id, key, undefined));
          released.push(pledge);
        } catch (err) {
          failed.push({ pledge, message: err instanceof Error ? err.message : String(err) });
        }
      }
      sending.current.delete(milestoneId);
      patch(milestoneId, (row) => ({
        ...row,
        phase: "done",
        failed,
        releasedCount: row.releasedCount + released.length,
        releasedEur: sumEur([String(row.releasedEur), ...released.map((pledge) => pledge.amount_eur)]),
      }));
    },
    [patch],
  );

  const start = useCallback(
    (milestoneId: string, targets: PublicPledge[]) => {
      if (!targets.length || timers.current.has(milestoneId) || sending.current.has(milestoneId)) return;
      setReleases((all) => ({
        ...all,
        [milestoneId]: {
          phase: "counting",
          secondsLeft: UNDO_WINDOW_SECONDS,
          releasedCount: all[milestoneId]?.releasedCount ?? 0,
          releasedEur: all[milestoneId]?.releasedEur ?? 0,
          failed: [],
        },
      }));
      // Timed against a deadline, so a throttled timer still ends on time.
      const deadline = Date.now() + UNDO_WINDOW_SECONDS * 1000;
      timers.current.set(
        milestoneId,
        setInterval(() => {
          const left = Math.ceil((deadline - Date.now()) / 1000);
          if (left > 0) {
            patch(milestoneId, (row) => ({ ...row, secondsLeft: left }));
            return;
          }
          stopTimer(milestoneId);
          void send(milestoneId, targets);
        }, 200),
      );
    },
    [patch, send, stopTimer],
  );

  const undo = useCallback(
    (milestoneId: string) => {
      stopTimer(milestoneId);
      setReleases((all) => {
        const { [milestoneId]: row, ...rest } = all;
        // A retry that is undone keeps the record of what already went through.
        return row?.releasedCount ? { ...rest, [milestoneId]: { ...row, phase: "done" } } : rest;
      });
    },
    [stopTimer],
  );

  useEffect(() => {
    const running = timers.current;
    const onVisibility = () => {
      if (document.visibilityState !== "hidden") return;
      for (const milestoneId of [...running.keys()]) {
        stopTimer(milestoneId);
        patch(milestoneId, (row) => ({ ...row, phase: "cancelled" }));
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      for (const timer of running.values()) clearInterval(timer);
      running.clear();
    };
  }, [patch, stopTimer]);

  return { releases, start, undo };
}

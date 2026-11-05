import type { Plugin } from "vite";

export function bryntumInstalled(root?: string): boolean;
export function bryntumFallback(options?: { isInstalled?: (root: string) => boolean; root?: string }): Plugin;

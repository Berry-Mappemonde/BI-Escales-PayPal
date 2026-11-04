import { memo } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import { ALL_LAYER_CONFIG } from "../constants/layers.js";
import { useAtlasNotice } from "../hooks/useAtlasLookup.js";
import { isCapitainerieEmpty } from "../layers/catalogSource.js";

/**
 * The map layer pills (GRIB2, ZEE, ports, BI layers, science, seabed,
 * climatology). Since 19 Sept. 2026 they live folded in the tools sidebar:
 * « on n'a pas besoin de les voir, on a besoin de pouvoir les voir ».
 */
export const LayerToggles = memo(function LayerToggles({ maritimeLayers }) {
  const { t } = useLang();
  const atlas = useAtlasNotice();
  if (!maritimeLayers) return null;
  const climoMeta = [atlas.source, atlas.period].filter(Boolean).join(" · ");
  const harbourEmpty = isCapitainerieEmpty(maritimeLayers.countBiCapitaineries);
  return (
    <div className="flex flex-wrap gap-1" data-testid="layer-toggles">
      {atlas.unavailable ? (
        <span className="text-[9px] font-semibold text-amber-200/90 px-1.5 py-0.5" data-testid="climatology-unavailable">
          {t("climatologyUnavailable")}
        </span>
      ) : null}
      {ALL_LAYER_CONFIG.map(({ key, labelKey, titleKey, color, showKey, toggleKey, loadingKey, errorKey }) => {
        const active = maritimeLayers[showKey];
        const loading = maritimeLayers[loadingKey];
        const error = maritimeLayers[errorKey];
        const climo = key.startsWith("climo-");
        const empty = key === "capitaineries" && harbourEmpty;
        const titleBase = error ? `${t(titleKey)} : ${t("layerUnavailable")}` : t(titleKey);
        const title = climo && climoMeta ? `${titleBase} · ${climoMeta}` : titleBase;
        return (
          <button
            key={key}
            type="button"
            disabled={empty}
            onClick={() => {
              if (empty) return;
              maritimeLayers[toggleKey]((v) => !v);
            }}
            title={title}
            data-testid={`layer-${key}`}
            aria-pressed={active}
            className={[
              "flex items-center justify-center gap-1 px-1.5 py-0.5 rounded-full",
              "text-[9px] font-semibold transition-all duration-150 select-none",
              empty
                ? "bg-slate-800/20 text-white/25 border border-white/5 cursor-not-allowed"
                : active
                  ? "bg-slate-700/80 text-white border border-white/10"
                  : "bg-slate-800/30 text-white/40 border border-white/5 hover:text-white/70",
            ].join(" ")}
          >
            {loading
              ? <div className="w-1.5 h-1.5 rounded-full border border-white/30 border-t-white animate-spin flex-shrink-0" />
              : <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: active ? color : "transparent", border: `1.5px solid ${error ? "#ef4444" : color}` }} />}
            {t(labelKey)}
            {key === "climo-cyclones" && climoMeta ? (
              <span data-testid="climatology-atlas-meta">{climoMeta}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
});

/** How many layers are on — shown next to the folded title. */
export function activeLayerCount(maritimeLayers) {
  if (!maritimeLayers) return 0;
  return ALL_LAYER_CONFIG.filter(({ showKey }) => maritimeLayers[showKey]).length;
}

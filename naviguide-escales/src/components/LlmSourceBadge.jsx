import { memo } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import { isAiGeneratedSource, llmSourceLabel, llmSourceShowsBrands } from "../utils/llmSourceLabel.js";

/**
 * Source under generated text. The cascade source stays visible, including
 * a fallback (OpenRouter, Claude, NIM). Nemotron on Token Factory adds the
 * names NVIDIA and Nebius as text — no third-party logo.
 */
export const LlmSourceBadge = memo(function LlmSourceBadge({
  source,
  reviewedBy = null,
  label = null,
  testId = "llm-source",
  className = "",
  textOnly = false,
  hidden = false,
}) {
  const { t } = useLang();
  // `label` lets a caller name the model with its own mapping (film sources).
  const model = label || llmSourceLabel(source, t, reviewedBy);
  const aiGenerated = isAiGeneratedSource(source);
  const showBrands = llmSourceShowsBrands(source);
  const named = aiGenerated ? t("aiActGeneratedLabel", { model }) : model;
  // Film bar: one short "Models" line, still naming the model that answered.
  const line = textOnly ? `${t("filmModels")} · ${named}` : named;

  return (
    <div
      data-testid={testId}
      data-ai-generated={aiGenerated ? "true" : "false"}
      data-llm-source={source || ""}
      hidden={hidden || undefined}
      className={`flex flex-col gap-0.5 min-w-0 ${className}`.trim()}
    >
      <span className="text-xs text-white leading-snug">{line}</span>
      {showBrands ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-white leading-snug" data-testid={`${testId}-brands`}>
          <span>{t("llmBrandNvidia")}</span>
          <span aria-hidden="true">·</span>
          <span>{t("llmBrandNebius")}</span>
        </div>
      ) : null}
    </div>
  );
});

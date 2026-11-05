import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface MaskedSecretInputProps {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  testId: string;
  autoComplete?: "off" | "new-password";
  className?: string;
}

/** Treasurer and other secrets: masked by default, optional plain-text toggle. */
export function MaskedSecretInput({
  label,
  value,
  onChange,
  testId,
  autoComplete = "off",
  className,
}: MaskedSecretInputProps) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);

  return (
    <label className={className ? `masked-secret-field ${className}` : "masked-secret-field"}>
      {label}
      <span className="masked-secret-row">
        <input
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          data-testid={testId}
        />
        <button
          type="button"
          className="masked-secret-toggle"
          aria-pressed={visible}
          aria-label={visible ? t("common.hideSecret") : t("common.showSecret")}
          data-testid={`${testId}-visibility-toggle`}
          onClick={() => setVisible((prev) => !prev)}
        >
          {visible ? t("common.hideSecret") : t("common.showSecret")}
        </button>
      </span>
    </label>
  );
}

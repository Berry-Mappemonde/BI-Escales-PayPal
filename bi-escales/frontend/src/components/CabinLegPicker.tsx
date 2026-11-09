import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchSchedule } from "../api/escales";
import type { ScheduleLeg } from "../api/types";

export interface CabinLegPickerProps {
  value: string;
  onChange: (legId: string) => void;
  disabled?: boolean;
}

export function CabinLegPicker({ value, onChange, disabled }: CabinLegPickerProps) {
  const { t } = useTranslation();
  const [legs, setLegs] = useState<ScheduleLeg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchSchedule()
      .then((schedule) => {
        if (cancelled) return;
        setLegs((schedule?.legs || []).filter((leg) => String(leg?.id || "").trim()));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLegs([]);
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <p className="hint" data-testid="cabin-leg-picker-loading">{t("cabinLegPicker.loading")}</p>;
  }

  if (error) {
    return (
      <p className="notice error" data-testid="cabin-leg-picker-error">
        {t("cabinLegPicker.error")}: {error}
      </p>
    );
  }

  if (!legs.length) {
    return <p className="hint" data-testid="cabin-leg-picker-empty">{t("cabinLegPicker.empty")}</p>;
  }

  return (
    <fieldset
      className="cabin-leg-picker"
      data-testid="cabin-leg-picker"
      disabled={disabled}
    >
      <legend>{t("cabinLegPicker.label")}</legend>
      <p className="hint">{t("cabinLegPicker.hint")}</p>
      <ul className="cabin-leg-picker-list">
        {legs.map((leg) => {
          const id = String(leg.id);
          const label = t("scheduler.cabinLeg", {
            from: leg.from_name || id,
            to: leg.to_name || "",
          });
          return (
            <li key={id}>
              <label>
                <input
                  type="radio"
                  name="cabin-leg-choice"
                  data-testid="cabin-leg-option"
                  data-leg-id={id}
                  value={id}
                  checked={value === id}
                  disabled={disabled}
                  onChange={() => onChange(id)}
                />
                {label}
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

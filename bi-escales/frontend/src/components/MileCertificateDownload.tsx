import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { PublicPledge } from "../api/types";
import { certificateAssetUrl, issueMileCertificate, mileCertificatePayerProof } from "../api/escales";

const SUCCESS = new Set(["authorized", "vaulted", "captured"]);

type Props = {
  pledge: PublicPledge | null;
  contributor?: string;
};

export function MileCertificateDownload({ pledge, contributor }: Props) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligible = Boolean(
    pledge
      && pledge.kind === "mile"
      && SUCCESS.has(pledge.status)
      && pledge.id,
  );

  useEffect(() => {
    setToken(null);
    setError(null);
    if (!eligible || !pledge) return undefined;
    let cancelled = false;
    setBusy(true);
    const payerProof = mileCertificatePayerProof(pledge);
    if (!payerProof) {
      setError(t("certificate.error"));
      setBusy(false);
      return undefined;
    }
    void issueMileCertificate(pledge.id, payerProof, contributor?.trim() || undefined, lang)
      .then((body) => {
        if (!cancelled) setToken(body.token);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : t("certificate.error"));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [eligible, pledge, contributor, lang, t]);

  if (!eligible) return null;

  return (
    <section className="stop-section mile-certificate-receipt" data-testid="mile-certificate-receipt">
      <h4>{t("certificate.heading")}</h4>
      {busy ? <p className="stop-note">{t("certificate.preparing")}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
      {token ? (
        <p className="mile-certificate-actions">
          <a
            data-testid="mile-certificate-png"
            href={certificateAssetUrl(token, "png", lang)}
            download
          >
            {t("certificate.downloadPng")}
          </a>
          {" · "}
          <a
            data-testid="mile-certificate-pdf"
            href={certificateAssetUrl(token, "pdf", lang)}
            download
          >
            {t("certificate.downloadPdf")}
          </a>
        </p>
      ) : null}
    </section>
  );
}

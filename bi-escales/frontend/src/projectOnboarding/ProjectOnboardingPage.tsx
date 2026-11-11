import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  captureOnboardingDonation,
  createOnboardingDonation,
  fetchOnboardingFeatureStatus,
  fetchProjectOnboarding,
  type ProjectOnboardingStatus,
} from "../api/projectOnboarding";
import "./project-onboarding.css";

const PENDING_KEY = "escales_onboard_donation_id";

function currentLang(i18nLang: string): string {
  return i18nLang.toLowerCase().startsWith("en") ? "en" : "fr";
}

export function ProjectOnboardingPage({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const lang = currentLang(i18n.language);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [view, setView] = useState<ProjectOnboardingStatus | null>(null);
  const [amount, setAmount] = useState("10.00");
  const [contributor, setContributor] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const data = await fetchProjectOnboarding(projectId, lang);
    setView(data);
  }, [projectId, lang]);

  useEffect(() => {
    void fetchOnboardingFeatureStatus().then((st) => setEnabled(st.enabled));
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void reload();
  }, [enabled, reload]);

  useEffect(() => {
    const pending = sessionStorage.getItem(PENDING_KEY);
    if (!pending || !enabled) {
      return;
    }
    sessionStorage.removeItem(PENDING_KEY);
    void (async () => {
      setBusy(true);
      try {
        await captureOnboardingDonation(pending);
        await reload();
        setNote(t("projectOnboarding.captureDone"));
      } catch {
        setNote(t("projectOnboarding.captureError"));
      } finally {
        setBusy(false);
      }
    })();
  }, [enabled, reload, t]);

  const onDonate = async (event: FormEvent) => {
    event.preventDefault();
    if (!view) {
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const returnUrl = `${window.location.origin}/projects/${encodeURIComponent(projectId)}/onboarding?paypal=return`;
      const cancelUrl = `${window.location.origin}/projects/${encodeURIComponent(projectId)}/onboarding?paypal=cancel`;
      const donation = await createOnboardingDonation(projectId, {
        amount_eur: amount,
        contributor: contributor.trim() || undefined,
        lang,
        return_url: returnUrl,
        cancel_url: cancelUrl,
      });
      if (donation._id) {
        sessionStorage.setItem(PENDING_KEY, donation._id);
      }
      const link = donation.approve_link;
      if (link) {
        window.location.href = link;
        return;
      }
      setNote(t("projectOnboarding.missingApproveLink"));
    } catch {
      setNote(t("projectOnboarding.donationError"));
    } finally {
      setBusy(false);
    }
  };

  if (enabled === false) {
    return <p className="notice warn">{t("projectOnboarding.featureOff")}</p>;
  }
  if (!view) {
    return <p>{t("projectOnboarding.loading")}</p>;
  }

  return (
    <main className="project-onboarding-page" data-testid="project-onboarding-page">
      <p className="sandbox-banner">{t("projectOnboarding.sandboxBanner")}</p>
      <header className="project-onboarding-card">
        {view.image_url ? (
          <img
            className="project-onboarding-logo"
            src={view.image_url}
            alt=""
            data-testid="project-onboarding-logo"
          />
        ) : null}
        <div className="project-onboarding-card-body">
          <h1>{view.title}</h1>
          {view.description ? <p className="project-onboarding-description">{view.description}</p> : null}
          {view.location_label ? (
            <p className="project-onboarding-location" data-testid="project-onboarding-location">
              {view.location_label}
            </p>
          ) : null}
        </div>
      </header>
      <p>{t(`projectOnboarding.projectStatus.${view.onboarding_status}`, { defaultValue: view.onboarding_status })}</p>
      <ul className="project-onboarding-donations">
        {view.donations.map((row) => (
          <li key={row.id} data-status={row.status}>
            <strong>{row.amount_eur} EUR</strong> — {t(row.status_label_key, { defaultValue: row.status })}
            {row.deadline_at ? (
              <span className="deadline"> {t("projectOnboarding.deadline", { date: row.deadline_at })}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {view.onboarding_link ? (
        <p>
          <a href={view.onboarding_link} rel="noreferrer" target="_blank">
            {t("projectOnboarding.openOnboardingLink")}
          </a>
        </p>
      ) : null}
      <form className="project-onboarding-donate" onSubmit={(e) => void onDonate(e)}>
        <p className="wallet-only">{t("projectOnboarding.walletOnly")}</p>
        <label>
          {t("pledge.amount")}
          <input data-testid="onboard-amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          {t("pledge.contributor")}
          <input value={contributor} onChange={(e) => setContributor(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || view.onboarding_status === "onboarded"} data-testid="onboard-donate">
          {t("projectOnboarding.donatePayPal")}
        </button>
      </form>
      {note ? <p className="notice">{note}</p> : null}
    </main>
  );
}

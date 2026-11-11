export type ProjectOnboardingStatus = {
  id: string;
  demo_fake?: boolean;
  title: string;
  description?: string;
  image_url?: string;
  location_label?: string;
  lat?: number;
  lng?: number;
  onboarding_status: string;
  onboarded_at?: string | null;
  donations: Array<{
    id: string;
    amount_eur: string;
    status: string;
    status_label_key: string;
    deadline_at?: string | null;
  }>;
  onboarding_link?: string | null;
  wallet_only: boolean;
  card_fields_hidden: boolean;
};

export type OnboardingDonation = {
  _id: string;
  approve_link?: string;
  order_id?: string;
  status: string;
  amount_eur: string;
};

function url(path: string): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
}

export async function fetchOnboardingFeatureStatus(): Promise<{ enabled: boolean; demo_project_id: string }> {
  try {
    const res = await fetch(url("/api/escales/project-onboarding/status"));
    if (!res.ok) {
      return { enabled: false, demo_project_id: "" };
    }
    return res.json();
  } catch {
    return { enabled: false, demo_project_id: "" };
  }
}

export async function fetchProjectOnboarding(projectId: string, lang: string): Promise<ProjectOnboardingStatus | null> {
  const res = await fetch(url(`/api/escales/project-onboarding/projects/${encodeURIComponent(projectId)}`), {
    headers: { "Accept-Language": lang },
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`onboarding project ${res.status}`);
  }
  return res.json();
}

export async function createOnboardingDonation(
  projectId: string,
  body: { amount_eur: string; contributor?: string; lang: string; return_url?: string; cancel_url?: string },
): Promise<OnboardingDonation> {
  const res = await fetch(url(`/api/escales/project-onboarding/projects/${encodeURIComponent(projectId)}/donations`), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept-Language": body.lang },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`donation ${res.status}`);
  }
  return res.json();
}

export async function captureOnboardingDonation(donationId: string): Promise<OnboardingDonation> {
  const res = await fetch(url(`/api/escales/project-onboarding/donations/${encodeURIComponent(donationId)}/capture`), {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`capture ${res.status}`);
  }
  return res.json();
}

export async function copyOnboardingLink(projectId: string, adminKey: string): Promise<string> {
  const res = await fetch(url(`/api/escales/project-onboarding/projects/${encodeURIComponent(projectId)}/onboarding-link/copy`), {
    headers: { "x-admin-key": adminKey },
  });
  if (!res.ok) {
    throw new Error(`copy link ${res.status}`);
  }
  const data = await res.json();
  return String(data.action_url || "");
}

export function emailPreviewUrl(projectId: string, lang: string): string {
  return url(`/api/escales/project-onboarding/projects/${encodeURIComponent(projectId)}/email/preview?lang=${encodeURIComponent(lang)}`);
}

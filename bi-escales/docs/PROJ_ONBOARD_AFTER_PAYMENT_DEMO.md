# PROJ onboard after payment — demo script (~20 s)

Evidence screenshots for criterion C9 are captured on test2 by the tester under `evidence/PROJ-ONBOARD-AFTER-PAYMENT/` (not in this PR).

## FR (Synthesia / voice, ~20 s)

1. Sur le projet fictif **Projet Démo — Récif Vivant**, un donateur paie en bac à sable PayPal uniquement.
2. Le don s’affiche : **En attente d’inscription du projet**, avec une échéance à 30 jours.
3. Le contact reçoit (ou l’admin prévisualise) un e-mail avec le bouton **Créer un compte PayPal Business**.
4. PayPal sandbox ouvre **Set up your business account** ; au retour, BI Escales affiche **Inscrit**.

## EN (Synthesia / voice, ~20 s)

1. On the fictional **Demo Project — Living Reef**, a supporter pays via PayPal sandbox wallet only.
2. The donation shows **Held pending project onboarding**, with a 30-day deadline.
3. The project contact gets (or the treasurer previews) an email with **Set up PayPal Business account**.
4. PayPal sandbox opens **Set up your business account**; returning to BI Escales shows **Onboarded**.

## Operator notes

- Contact email on test2 only: env `ESCALES_DEMO_PROJECT_CONTACT_EMAIL` (placeholder in docs: `<CLEMENT_EMAIL>`).
- Tests use `project@example.com` only.
- Toggle **Onboard After Payment** on app `APP-9RY91696GH803810X` remains **BLOCKED_ON_CLEMENT**; the C4 fallback path must pass without it.
- **Partner Referrals** (`POST /v2/customer/partner-referrals`) needs a sandbox **platform** app whose REST credentials (`PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` on test2) include the **Partner Referrals** permission. Without it, PayPal may return **403**; donations still succeed (order saved) but `onboarding_link.available` is `false` until permission is granted or a link is created another way.
- Onboarding return uses PayPal **merchant-integrations** (tracking lookup, then seller status). Set `PAYPAL_PARTNER_MERCHANT_ID` on test2; query-string `merchantId` is **not** trusted for marking a project onboarded.

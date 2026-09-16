# Billing: Asaas

This document describes the monetization architecture of MemoBelc.

## Decisions

- **Asaas is the only payment provider** for new purchases on web, Android and iOS: subscriptions, one-time book purchases, bundle purchases, course checkouts, PIX, credit card, coupons and refunds.
- Checkout: **PIX is native in the app** (QR + copy-paste). **Credit card opens the Asaas hosted invoice** (`invoiceUrl` / `checkout_url`). Card data is never collected in the app on new purchases.
- **Google Play Billing is legacy.** Existing Play subscriptions keep working (`/billing/google/verify` and RTDN). New checkouts never return a Play SKU.
- **Stripe is disabled.** `STRIPE_*` variables are optional. `/payment/payment_intent` returns `410`.
- Book invoices include title, author, language, level, genre and chapters. After `PAYMENT_CONFIRMED` or a client sync, the book is granted to the buyer's library.
- External checkout is tied to a **classroom**. An admin must set `checkout_allowed` on the classroom. Then the teacher (owner) can set `checkout_enabled` + `price` and copy `{FRONT_BASE_URL}/checkout/{classroomId}`. Sales pages on Memobelc Page should point to that URL.
- `POST /billing/public/checkout` with `product_type: "classroom"` is always a guest checkout: only **email + CPF** (no password, no login). New buyers get a profile with password = CPF and `must_change_password`. Existing buyers are linked by email or CPF. After payment, both receive a welcome + purchase confirmation email with access instructions. PIX polling uses `/billing/public/payments/{id}/sync` with the same email and CPF.

## How access works

Entitlements are the single source of truth. A user can access a service or book if **any** of these is valid:

1. An active/trialing subscription (Asaas, or a leftover Google Play subscription), including a 48h grace window after `next_due_date` when status is pending/overdue.
2. A confirmed one-time purchase.
3. A manual grant from an admin.
4. An external sale recorded by an admin.

There is **at most one paid active subscription per user**. Upgrade/downgrade stays on Asaas. A leftover Play subscription must be cancelled in the Play Store before starting an Asaas plan.

## Native checkout

`POST /billing/checkout` requires `billing_type`: `PIX` or `CREDIT_CARD`, plus `cpf_cnpj`.

| Method | Flow |
|--------|------|
| PIX | Asaas charge with due date today. Response includes `pix.encoded_image`, `pix.payload` and `payment._id`. The app shows the QR, copies the code and polls `POST /billing/payments/{id}/sync`. `GET /billing/payments/{id}/pix` refreshes an expired QR. |
| CREDIT_CARD | Creates a pending Asaas charge and returns `checkout_url` (`invoiceUrl`). The app opens the Asaas hosted checkout. Access is granted after `PAYMENT_CONFIRMED` or a client sync. |

The first Asaas invoice of a plan is stored as a `PaymentModel` so PIX polling uses the same sync endpoint.

`POST /billing/update-payment` with `credit_card` updates the card on an Asaas subscription. Leftover Play subscribers still receive `manage_url`.

## Environment variables

```
ASAAS_API_KEY=
ASAAS_API_URL=https://api-sandbox.asaas.com/v3
ASAAS_WEBHOOK_TOKEN=

GOOGLE_PLAY_PACKAGE_NAME=com.anonymous.memobelc
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=
GOOGLE_PLAY_SERVICE_ACCOUNT_FILE=
GOOGLE_PLAY_RTDN_TOKEN=

```

Production Asaas URL: `https://api.asaas.com/v3`.

Play variables are optional and only needed to keep existing Play subscriptions in sync.

## External setup

1. Create an Asaas account (sandbox then production).
2. Register a webhook pointing to `{API_URL}/billing/asaas/webhook` with header token `ASAAS_WEBHOOK_TOKEN`. Subscribe to payment and subscription events.
3. Google Play RTDN remains optional for leftover Play subscriptions: `{API_URL}/billing/google/rtdn?token={GOOGLE_PLAY_RTDN_TOKEN}`.

## Main API routes

- `GET /plans/public` — catalog
- `GET /classroom/public/{id}` — public classroom offer (only if admin allowed and teacher enabled checkout)
- `POST /billing/checkout` — `{ product_type, product_id, platform, coupon_code, billing_type, cpf_cnpj, credit_card }` (`product_type`: plan, book, bundle, course, classroom)
- `POST /billing/public/checkout` — guest classroom checkout (never uses a logged-in session): `{ product_type: "classroom", product_id, name, email, billing_type, cpf_cnpj, credit_card }`. New users get password = CPF/CNPJ digits and `must_change_password: true`. Existing users are matched by email with no password check. Returned JWT is only for PIX polling, not app login.
- `PUT /auth/change_password` — `{ current_password, new_password }` (Bearer). Required on first login after a checkout-created account. New password cannot be the CPF.
- `GET /billing/payments/{id}/pix` — refresh PIX QR
- `POST /billing/payments/{id}/sync` — poll payment (books, bundles and first plan invoice)
- `GET /billing/me` and `GET /entitlements/me`
- `POST /billing/cancel`, `POST /billing/change-plan`, `POST /billing/update-payment`
- `POST /billing/google/verify` — leftover Play purchases only
- Admin: `/plans/admin`, `/coupons/admin`, `/bundles/admin`, `/admin/billing/*`
- `GET /admin/billing/classrooms` — list classrooms and checkout flags
- `PUT /admin/billing/classrooms/{id}` — admin sets `checkout_allowed`
- `GET /admin/billing/classroom-checkouts` — classroom checkout history and receipts (`receipt_url`)

Default service visibility is **allow for everyone**. Admin can set each service to **allow** (visible to everyone), **disabled** (visible, not clickable), **disabled_upgrade** (paywalled until the user has an active plan), or **hide** (not shown in the menu). `redirect_plans` is treated as `disabled_upgrade`.

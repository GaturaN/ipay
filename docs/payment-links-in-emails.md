# Payment Links in Emails

Put a **"Pay now"** link into any invoice or reminder email. The customer clicks it, lands on a
no-login page showing their live balance, and prompts *themselves* to pay by M-Pesa (or hosted
checkout). It's the same tokenised `/pay` link the Collect app shares — just generated at
send time.

---

## Prerequisite

Turn on **iPay Settings → Use Hosted Checkout Redirect** (`enable_redirect`). This is the master
switch for every payment link. With it off, the helper returns nothing and no link appears —
the email just omits the button.

Link validity is **iPay Settings → Payment Link TTL Days** (default 7).

## Add the link to your own ERPNext emails

iPay registers a Jinja helper, `ipay_payment_link(invoice)`, available in **any** Email Template,
Notification, or Print Format. Drop this into the message body:

```jinja
{% set link = ipay_payment_link(doc.name) %}
{% if link %}
  <a href="{{ link }}"
     style="background:#007a36;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;">
    Pay now
  </a>
{% endif %}
```

It returns the URL for the invoice, or **nothing** when there's no balance to collect — so the
`{% if link %}` guard cleanly hides the button when it doesn't apply (see *When there's no link*).

## Or use the emails iPay ships

iPay ships two ready-made **Notifications** (Desk → *Notification*), **disabled by default** and
fully editable — enable, edit, or delete them freely (they're created once and never
re-synced):

| Notification | Fires | Note |
|---|---|---|
| **iPay: Invoice Issued** | when a Sales Invoice is submitted | includes the Pay now link |
| **iPay: Payment Reminder** | 3 days after the due date, while unpaid | change the days / wording in the Desk |

Both email the invoice's `contact_email` and skip fully-paid invoices. They're a starting point —
adjust the copy (e.g. add your M-Pesa Paybill instructions) before enabling.

## How the link behaves

- **One link per invoice, idempotent.** Generating it again (a reminder run, a re-send) reuses
  the same request and token — the customer always gets the same link, not a new one each time.
- **Always shows the live balance.** A partly-paid invoice shows the remaining amount.
- **Self-managing.** The `/pay` page handles every state: **paid** → "Thank you", **expired** →
  "request a new one", **cancelled / cheque received** → the right message.

### When there's no link

`ipay_payment_link` returns nothing (so the button is hidden) when:

- the master switch is off,
- the invoice is fully paid, not submitted, or has no balance,
- a **cheque** has already been collected for it, or
- the invoice is **prepaid** (settles automatically — no iPay request is needed).

## Security

The link carries only a 24-character random token tied to that one invoice/bundle. A recipient
opens the `/pay` page and pays **without logging in**; they can't reach anything else, and the
guest pay endpoint is rate-limited per token. Cancelled, expired, and cheque-covered tokens are
refused.

## Files

| Area | Path |
|---|---|
| Link function + `/pay` flow | `ipay/ipay/main/utils/ipay_redirect.py` (`payment_link_for_invoice`) |
| Jinja helper | `ipay/ipay/main/utils/jinja.py` (`ipay_payment_link`), registered in `ipay/hooks.py` |
| Shipped notifications | `ipay/patches/v1_0/create_payment_email_notifications.py` |
| Customer pay page | `ipay/www/pay.py` (route `/pay`) |

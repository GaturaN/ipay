# Cheque Collection

A collector records a customer's cheque from the Collect app. The app **never submits** the
payment — it writes a **draft** Payment Entry with the cheque photo attached, and the accounts
team reviews and submits it. Until they do, no money is considered received.

---

## Settings

All under **iPay Settings**.

| Setting | What it does |
|---|---|
| **Allow Cheque Collection** | Master switch. Off (default) → no cheque option appears anywhere. |
| **Cheque Per Invoice** | On (default) → a cheque can be attached to specific invoices. Off → every cheque is customer-level (on account, no invoice attached); the per-invoice buttons disappear. |
| **Cheque Account** | The account collected cheques are booked to (undeposited funds). **Required** before any cheque can be recorded — cheques never book to cash. |

The cheque option only shows in the app when **Allow Cheque Collection is on *and* a Cheque Account
is set**. Toggling these takes effect on the next app load (reload / reopen the PWA).

---

## How a cheque is recorded

1. **Capture** — photograph the cheque (required), enter the amount and the cheque number.
2. **Confirm** — a summary that reads differently for each mode (see below), with the draft caveat.
3. **Recorded** — a confirmation that says *recorded*, never *paid*.

Two modes, decided by whether invoices were ticked (only when *Cheque Per Invoice* is on):

- **Against invoices** — the cheque references the ticked invoices, allocated oldest-first. Those
  cards show an amber *"awaiting cheque"* notice and lose their prompt buttons.
- **On account** — nothing ticked (or *Cheque Per Invoice* is off). The cheque references no
  invoice; the customer header carries an amber *on-account* notice. Accounts decide later which
  invoices it settles.

## After recording — why it can't be collected twice

A draft Payment Entry does **not** reduce an invoice's outstanding, so a collected cheque leaves
its invoices looking unpaid. The app therefore blocks re-charging them: an invoice a cheque covers
is refused on **every** rail — M-Pesa prompt, hosted checkout, the payment link, and bundling —
until the draft is submitted or cancelled. The on-account figure on the customer header is the
equivalent guard for cheques that name no invoice.

## What accounts receives

A draft Payment Entry shaped like the ones they already create by hand:

- `docstatus = 0` (Draft), `mode_of_payment = Cheque`, booked to the Cheque Account.
- `reference_no = <cheque number>-<customer>` (see *Reference number format* below).
- Invoice references (allocated oldest-first) for a per-invoice cheque; none for an on-account one.
- The cheque photo attached as a private file.
- Owner = the collector who recorded it.

---

## Known limitations & operational notes

These are deliberate trade-offs, documented so the accounts/ops team knows the process. They are
tracked for possible future work in issue **#88**.

### A bounced or un-actioned cheque
Once a cheque is recorded, its invoices cannot be collected in the app until the draft is dealt
with. There is **no automatic expiry** — this is intentional (a cheque marker means money was
taken, and auto-expiring it could re-open collection of money that really was collected).

**If a cheque bounces or was recorded in error:** accounts should **cancel or delete the draft
Payment Entry**. That immediately returns the invoice to the collection list.

### Correcting a mistaken cheque
`reference_no` has a unique index, so a **cancelled** cheque still holds its number and the same
number can't be re-recorded for that customer.

**To re-record a cheque entered wrongly (wrong amount, etc.):** **delete** the draft rather than
cancelling it — deleting frees the number so it can be re-entered. (A genuine replacement cheque
has a different number, so this only matters for correcting a data-entry mistake.)

### A cheque that won't submit because the balance changed
A per-invoice cheque's allocation is fixed when the collector records it. If the customer part-pays
those invoices another way (e.g. M-Pesa) before accounts submit the cheque, the draft's allocation
may exceed the reduced outstanding and ERPNext will refuse to submit it.

**Accounts should adjust the references on the draft** (standard ERPNext) before submitting.

### Reference number format
Accounts see `reference_no` as `001894-Customer Name`, not the bare `001894`. This is deliberate:
cheque numbers are short and repeat across banks, and the unique index would otherwise refuse two
different customers' cheque 001894. **Confirm this format is acceptable to the accounts team** — if
not, the alternative is to capture the bank (e.g. `KCB/001894`).

### Invoices whose payment schedule is stale
A few invoices have a payment schedule whose terms sum to **less** than the invoice still owes
(a data inconsistency). A full payment on such an invoice allocates what the terms allow and leaves
the rest as **customer credit** — the invoice keeps showing the small balance. This cannot be fixed
in the payment code (ERPNext will not let any allocation clear it); the fix is to **correct the
invoice's payment schedule**. Rare, and currently none exist.

### Restricted sales managers and the on-account figure
When *Restrict Sales Managers to Their Own Book* is on, a sales manager is confined to their own
customers on the sales page — but the on-account cheque figure is not scoped for them there. This
is a minor consistency gap, not an exposure: a sales manager can already read any customer's
figure through the internal page.

---

## For developers

- The app never submits a cheque Payment Entry; it inserts a **draft** (`docstatus 0`).
- iPay roles hold no Payment Entry permission — `record_cheque` inserts as Administrator inside a
  `try/finally`, with the collector restored as `owner`. The guards (`_require_operator`,
  `_require_invoice_access`, `_require_customer_access`) are the authorisation.
- Collect invoices use **Cash on Delivery / End of Day** templates, both with
  `allocate_payment_based_on_payment_terms = 1`. On these, ERPNext **rejects a Payment Entry
  reference that has no payment term** — so allocation must always carry a payment term, and the
  stale-schedule shortfall above cannot be forced onto the invoice.
- The "already covered by a cheque" question is answered once, in
  `ipay/ipay/main/utils/cheque.py::awaiting_cheque_amounts`, and reused by the card markers and the
  charge guards so they cannot drift.
- Settings flags (`allow_cheque`, `cheque_per_invoice`, `enable_redirect`) are read **fresh**, not
  through the doc cache, so toggles take effect immediately.

import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime, today

from ipay.ipay.main.utils.prepaid import all_prepaid_invoice_names, prepaid_invoice_names
from ipay.ipay.main.utils.collector import OPERATOR_ROLES, collector_scope, is_collector_only, my_driver_ids
from ipay.ipay.main.utils.cheque import awaiting_cheque_amounts
from ipay.ipay.main.utils.cheque_due import (
    all_open_dues,
    open_due_for_customer,
    open_dues_for_customers,
    open_dues_for_driver,
)
from ipay.ipay.main.utils.constants import (
    ACTIVE_BUNDLE_WINDOW_MIN,
    CHEQUE_MODE,
    note_filters,
    note_text,
)
from ipay.ipay.main.utils.sales import (
    SALES_MANAGER_ROLES,
    SALES_ROLE,
    customers_in_book,
    is_sales_only,
    my_sales_person,
    sales_person_options,
    scope_to_sales_person,
)

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User", "iPay Collector"}
# Internal mode: every customer, all terms, filterable by sales person — so a sales manager
# belongs here rather than on a member's own page.
INTERNAL_ROLES = OPERATOR_ROLES | {"Sales Manager"}
# Who may load the SPA shell. A sales member is deliberately NOT in ALLOWED_ROLES: that set
# gates the field endpoints, which scope by collector and would hand a sales member the whole
# collect-on-delivery book. They reach their data through the sales endpoints below.
PAGE_ROLES = ALLOWED_ROLES | INTERNAL_ROLES | {SALES_ROLE}


def _drop_bundled(invoices):
    """Hide an invoice from the collection list ONLY while it is actively being
    collected via a bundle — a submitted (docstatus=1), still-Pending iPay Request
    created within the last ACTIVE_BUNDLE_WINDOW_MIN minutes. The instant a bundle is
    cancelled (docstatus 2 — split/discarded), abandoned, settles short
    (Underpaid/Overpaid/Failed), or just goes stale unpaid, its member invoices
    return to the list, so a bundle can never strand them."""
    if not invoices:
        return invoices
    rows = frappe.get_all(
        "iPay Request Invoice",
        filters={"sales_invoice": ["in", [inv.name for inv in invoices]]},
        fields=["sales_invoice", "parent"],
    )
    if not rows:
        return invoices
    cutoff = add_to_date(now_datetime(), minutes=-ACTIVE_BUNDLE_WINDOW_MIN)
    active = set(frappe.get_all(
        "iPay Request",
        filters={
            "name": ["in", list({r.parent for r in rows})],
            "docstatus": 1,
            "status": "Pending",
            "creation": [">=", cutoff],
        },
        pluck="name",
    ))
    bundled = {r.sales_invoice for r in rows if r.parent in active}
    return [inv for inv in invoices if inv.name not in bundled]


def _sum_outstanding(extra_filters=None):
    """Sum of outstanding on submitted, non-return, unpaid Sales Invoices."""
    filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}
    if extra_filters:
        filters.update(extra_filters)
    rows = frappe.get_all("Sales Invoice", filters=filters, fields=["sum(outstanding_amount) as total"])
    return flt(rows[0].total) if rows else 0


def _collected_totals(today_date, request_names=None):
    """Collected via iPay = paid_amount of Payment Entries linked from iPay
    Requests. Returns (overall, today). When request_names is given (collector
    view), restrict to those requests."""
    scope_clause = ""
    params = {"today": today_date}
    if request_names is not None:
        if not request_names:
            return (0, 0)
        scope_clause = "and ir.name in %(reqs)s"
        params["reqs"] = tuple(request_names)
    row = frappe.db.sql(
        f"""
        select
            coalesce(sum(pe.paid_amount), 0) as total,
            coalesce(sum(case when pe.posting_date = %(today)s then pe.paid_amount else 0 end), 0) as today_total
        from `tabPayment Entry` pe
        inner join `tabiPay Request` ir on ir.payment_entry = pe.name
        where pe.docstatus = 1 {scope_clause}
        """,
        params,
        as_dict=True,
    )
    return (flt(row[0].total), flt(row[0].today_total)) if row else (0, 0)


def lands_on_sales(user=None):
    """True when the sales page is this login's home: the sales team, users and managers
    alike. iPay operators land on internal instead, which also carries the driver filter.
    Drives both the /collect_payments redirect and the SPA's own routing."""
    roles = set(frappe.get_roles(user or frappe.session.user))
    if OPERATOR_ROLES & roles:
        return False
    return bool({SALES_ROLE, "Sales Manager"} & roles)


def _require_collection_access(roles=None):
    """Operators and collectors only. Guests are redirected to login by callers. `roles`
    widens the set for an endpoint shared with another page."""
    if frappe.session.user == "Guest" or not ((roles or ALLOWED_ROLES) & set(frappe.get_roles())):
        frappe.throw("You are not permitted to collect payments.", frappe.PermissionError)


def _annotate_delivery(invoices):
    """Attach delivery_note and driver(s) to each invoice in place (two batched
    queries). The driver lives on the Delivery Note, not the Sales Invoice; an
    invoice may span several delivery notes / drivers, so all are kept."""
    if not invoices:
        return
    names = [inv.name for inv in invoices]
    links = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": ["in", names], "delivery_note": ["is", "set"]},
        fields=["parent", "delivery_note"],
    )
    dn_map = {}
    for link in links:
        dn_map.setdefault(link.parent, set()).add(link.delivery_note)

    dn_names = {n for note_set in dn_map.values() for n in note_set}
    driver_by_dn = {}
    if dn_names:
        for dn in frappe.get_all(
            "Delivery Note", filters={"name": ["in", list(dn_names)]}, fields=["name", "driver_name"]
        ):
            driver_by_dn[dn.name] = dn.driver_name or ""

    for inv in invoices:
        dns = sorted(dn_map.get(inv.name, []))
        inv.delivery_note = ", ".join(dns)
        inv.drivers = sorted({driver_by_dn[n] for n in dns if driver_by_dn.get(n)})
        inv.driver_name = ", ".join(inv.drivers)


def _collectable_terms():
    """Payment Terms Templates the Collect app is scoped to (iPay Settings → Collect
    Payment Terms) — the terms drivers settle on delivery. Empty means no term filter,
    so every outstanding invoice is collectable (behaviour before the setting existed).

    Read fresh from the child rows, not the doc cache — a cached read would keep the old terms
    after the setting changes (same reason _settings_flags reads the flags fresh)."""
    return frappe.get_all(
        "iPay Collection Payment Term",
        filters={"parenttype": "iPay Settings", "parentfield": "collect_payment_terms"},
        pluck="payment_terms_template",
    )


def _settings_flags():
    """The iPay Settings every collection response carries: hosted-checkout availability, the
    M-Pesa STK ceiling, and whether cheque collection is on. Read fresh, exactly like
    enable_redirect — a cached read would keep showing the old value after the setting is toggled."""
    return {
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
        "mpesa_max": flt(frappe.db.get_single_value("iPay Settings", "mpesa_max_amount")),
        "allow_cheque": bool(frappe.db.get_single_value("iPay Settings", "allow_cheque_collection")),
        "cheque_per_invoice": bool(frappe.db.get_single_value("iPay Settings", "cheque_per_invoice")),
    }


def _outstanding_si_filters(user):
    """Base filters for the Sales Invoices `user` may collect — restricted to the
    configured collect-on-delivery payment terms, their own book if a collector, and a
    positive balance."""
    si_filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}
    terms = _collectable_terms()
    if terms:
        si_filters["payment_terms_template"] = ["in", terms]
    if is_collector_only(user):
        si_filters["name"] = ["in", list(collector_scope(user)["invoices"]) or ["__none__"]]
    return si_filters


def _outstanding_invoices(user, customer=None):
    """Cleaned outstanding Sales Invoice rows — prepaid and actively-bundled dropped,
    oldest first, uncapped, optionally for one customer. Minimal fields; callers
    annotate delivery/phone as needed."""
    si_filters = _outstanding_si_filters(user)
    if customer:
        si_filters["customer"] = customer
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date", "due_date", "payment_terms_template"],
        order_by="posting_date asc",
        limit_page_length=0,
    )
    prepaid = prepaid_invoice_names([inv.name for inv in invoices])
    if prepaid:
        invoices = [inv for inv in invoices if inv.name not in prepaid]
    return _drop_bundled(invoices)


def _accumulate_customer(row_map, inv):
    """Get-or-create inv's customer row and add its amount + count. Returns the row so the
    caller can attach its own extra fields (search keywords, latest date)."""
    row = row_map.get(inv.customer)
    if row is None:
        row = row_map[inv.customer] = {
            "customer": inv.customer,
            "customer_name": inv.customer_name or inv.customer,
            "total_outstanding": 0.0,
            "invoice_count": 0,
        }
    row["total_outstanding"] += flt(inv.outstanding_amount)
    row["invoice_count"] += 1
    return row


def _group_customers(invoices):
    """Group outstanding invoices by customer — total owed, count, and search keywords
    (each invoice's number and delivery note, so the list can be searched by either) —
    most-owed first. Invoices must already be delivery-annotated."""
    by_customer = {}
    for inv in invoices:
        row = _accumulate_customer(by_customer, inv)
        row.setdefault("keywords", []).append(inv.name)
        if inv.get("delivery_note"):
            row["keywords"].append(inv.delivery_note)
    return sorted(by_customer.values(), key=lambda r: r["total_outstanding"], reverse=True)


def _customer_invoices(user, customer, driver=None):
    """One customer's outstanding invoices, annotated for prompting (delivery, driver,
    on-file phone, collection notes). Optionally scoped to a single driver's deliveries."""
    invoices = _outstanding_invoices(user, customer)
    _annotate_delivery(invoices)
    if driver:
        invoices = [inv for inv in invoices if driver in (inv.get("drivers") or [])]
    _annotate_customer_phone(invoices)
    _annotate_sales_person(invoices)
    _annotate_notes(invoices)
    _annotate_awaiting_cheque(invoices)
    return invoices


def _annotate_customer_phone(invoices):
    """Attach each customer's on-file mobile number (batched) so the SPA can
    pre-fill it and let the operator confirm or change the number before every
    STK prompt — never silently charge a default."""
    customers = list({inv.customer for inv in invoices if inv.customer})
    if not customers:
        return
    phone_by_customer = {
        c.name: c.mobile_no or ""
        for c in frappe.get_all(
            "Customer", filters={"name": ["in", customers]}, fields=["name", "mobile_no"]
        )
    }
    for inv in invoices:
        inv.customer_phone = phone_by_customer.get(inv.customer, "")


def _annotate_sales_person(invoices):
    """Attach the sales team member(s) behind each invoice in place (two batched queries) —
    the invoice's own Sales Team plus its customer's, the same union the sales scoping matches,
    so a card shows who owns it and why it sits in that member's book. Both are kept because
    ERPNext snapshots the customer's team onto the invoice at creation and never refreshes it."""
    if not invoices:
        return
    by_invoice, by_customer = {}, {}
    for row in frappe.get_all(
        "Sales Team",
        filters={"parenttype": "Sales Invoice", "parent": ["in", [inv.name for inv in invoices]]},
        fields=["parent", "sales_person"],
    ):
        by_invoice.setdefault(row.parent, set()).add(row.sales_person)

    customers = list({inv.customer for inv in invoices if inv.customer})
    if customers:
        for row in frappe.get_all(
            "Sales Team",
            filters={"parenttype": "Customer", "parent": ["in", customers]},
            fields=["parent", "sales_person"],
        ):
            by_customer.setdefault(row.parent, set()).add(row.sales_person)

    for inv in invoices:
        people = by_invoice.get(inv.name, set()) | by_customer.get(inv.customer, set())
        inv.sales_persons = sorted(p for p in people if p)
        inv.sales_person_name = ", ".join(inv.sales_persons)


def _annotate_notes(invoices):
    """Attach each invoice's collection-note count and newest note (batched), so a card shows
    what was said without opening anything — and one query serves the page, never one per card."""
    names = [inv.name for inv in invoices]
    if not names:
        return
    notes = frappe.get_all(
        "Comment",
        filters=note_filters(["in", names]),
        fields=["reference_name", "content"],
        order_by="creation asc",
    )
    latest, counts = {}, {}
    for note in notes:
        counts[note.reference_name] = counts.get(note.reference_name, 0) + 1
        latest[note.reference_name] = note.content  # ascending, so the last seen is the newest
    for inv in invoices:
        inv.note_count = counts.get(inv.name, 0)
        inv.note_latest = note_text(latest.get(inv.name) or "")


def _annotate_awaiting_cheque(invoices):
    """Flag each invoice with the amount a collected cheque already covers, so the card can drop
    its prompt buttons. The amount rides along because a cheque may cover only part of the
    invoice, and a bare flag would read as though the whole balance were settled."""
    covered = awaiting_cheque_amounts([inv.name for inv in invoices])
    for inv in invoices:
        inv.awaiting_cheque = flt(covered.get(inv.name, 0))


def _cheque_on_account(customer):
    """What a customer has handed over in cheques that name no invoice. Nothing marks those
    invoices, so this is the only thing standing between an on-account cheque and collecting
    the same money twice.

    Scoped to the caller: the invoices in the same response are already scoped, so this figure
    must be too — a collector or sales member never sees it for a customer they cannot access.

    Any unallocated amount counts, not only fully-on-account cheques: a cheque that partly covers
    ticked invoices leaves the rest as customer credit, and that surplus is on account too."""
    from ipay.ipay.main.utils.collector import can_access_customer

    if not can_access_customer(customer):
        return 0.0
    amounts = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": customer,
            "docstatus": 0,
            "mode_of_payment": CHEQUE_MODE,
            "unallocated_amount": [">", 0],
        },
        pluck="unallocated_amount",
    )
    return flt(sum(amounts))


def get_context(context):
    """The collection UI now lives in the SPA. This legacy route just redirects:
    operators to internal mode (/collect/internal, all terms), field collectors to their
    scoped app (/collect), sales members to their own book (/collect/sales); guests log in
    first."""
    context.no_cache = 1
    if frappe.session.user == "Guest":
        # Back to this route (not straight to /collect/internal) so the role branch below
        # runs after login — a collector must land on /collect, not internal mode.
        frappe.local.flags.redirect_location = "/login?redirect-to=/collect_payments"
        raise frappe.Redirect
    user = frappe.session.user
    if lands_on_sales(user):
        frappe.local.flags.redirect_location = "/collect/sales"
        raise frappe.Redirect
    # Gate on the page set, not ALLOWED_ROLES: a sales manager belongs on internal but is not
    # a field-app role. Each destination re-gates itself.
    if not (PAGE_ROLES & set(frappe.get_roles(user))):
        frappe.throw("You do not have access to iPay Collect.", frappe.PermissionError)
    frappe.local.flags.redirect_location = (
        "/collect" if is_collector_only(user) else "/collect/internal"
    )
    raise frappe.Redirect


def _invoices_for_driver_name(driver_name):
    """Sales Invoices delivered by the driver of the given name (via their
    delivery notes)."""
    if not driver_name:
        return set()
    dns = frappe.get_all(
        "Delivery Note",
        filters={"driver_name": driver_name, "docstatus": 1},
        pluck="name",
    )
    if not dns:
        return set()
    return set(frappe.get_all(
        "Sales Invoice Item", filters={"delivery_note": ["in", dns]}, pluck="parent"
    ))


def _scope_to_driver(invoices, driver):
    """Keep only invoices delivered by the named driver (via their delivery notes). Used by
    the internal endpoints, which filter before annotating delivery data."""
    if not driver:
        return invoices
    delivered = _invoices_for_driver_name(driver)
    return [inv for inv in invoices if inv.name in delivered]


def _requests_for_invoices(invoices):
    """iPay Requests (single + bundle) covering any of the given invoices."""
    invoices = list(invoices or [])
    if not invoices:
        return []
    reqs = set(frappe.get_all(
        "iPay Request", filters={"sales_invoice": ["in", invoices]}, pluck="name"
    ))
    reqs.update(frappe.get_all(
        "iPay Request Invoice", filters={"sales_invoice": ["in", invoices]}, pluck="parent"
    ))
    return list(reqs)


@frappe.whitelist()
def collection_stats(driver=None, all_terms=0):
    """Today's collected + yet-to-collect totals, optionally scoped to a single
    driver (by name) — backs the driver filter on the collection page. Operator/
    collector gated; a collector is always restricted to their own book, so the
    driver argument can only narrow within it, never widen it. `all_terms` drops the
    collect-on-delivery term scope for the internal (all-terms) header."""
    # Backs the header on the field page AND internal mode, so it admits either page's roles —
    # a sales manager on internal would otherwise read a permanently-zero round.
    _require_collection_access(ALLOWED_ROLES | INTERNAL_ROLES)

    today_date = today()

    # Universe of invoices/requests the figures cover: a collector's own book,
    # else everything; narrowed to one driver when a driver is given.
    invoices = requests = None
    if is_collector_only(frappe.session.user):
        scope = collector_scope(frappe.session.user)
        invoices, requests = scope["invoices"], list(scope["requests"])

    if driver:
        driver_invoices = _invoices_for_driver_name(driver)
        invoices = driver_invoices if invoices is None else (invoices & driver_invoices)
        requests = _requests_for_invoices(invoices)
    elif invoices is not None and requests is None:
        requests = _requests_for_invoices(invoices)

    _, collected_today = _collected_totals(today_date, requests)
    out_filter = {"posting_date": today_date}
    # Scope "to go" to the same collect-on-delivery terms as the field customer list, so
    # the header total never counts credit invoices that never appear on the page. The
    # internal (all-terms) header passes all_terms to keep every term in the figure.
    terms = [] if cint(all_terms) else _collectable_terms()
    if terms:
        out_filter["payment_terms_template"] = ["in", terms]
    if invoices is not None:
        out_filter["name"] = ["in", list(invoices) or ["__none__"]]
    outstanding_today = _sum_outstanding(out_filter)

    return {"collected_today": collected_today, "outstanding_today": outstanding_today}


@frappe.whitelist()
def collection_customers(driver=None):
    """SPA top level: customers with an outstanding collect-on-delivery balance the
    caller may collect — each with total owed and invoice count, most-owed first — plus
    the driver options for the filter and the bundle/redirect flags. When `driver` is
    given, the customers and their totals are scoped to that driver's deliveries; the
    driver options stay the full list so the filter can still be changed."""
    _require_collection_access()
    invoices = _outstanding_invoices(frappe.session.user)
    _annotate_delivery(invoices)
    drivers = sorted({d for inv in invoices for d in (inv.get("drivers") or [])})
    if driver:
        invoices = [inv for inv in invoices if driver in (inv.get("drivers") or [])]
    return {
        "customers": _group_customers(invoices),
        "drivers": drivers,
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
        "can_bundle": not is_collector_only(frappe.session.user),
        # Flagged cheques under the same scope as the customers beneath them: a collector sees
        # only their own driver's, anyone who sees every customer sees every cheque. Both follow
        # the page's driver filter.
        "cheque_dues": (
            open_dues_for_driver(frappe.session.user, driver)
            if is_collector_only(frappe.session.user)
            else all_open_dues(driver)
        ),
    }


@frappe.whitelist()
def customer_collection(customer, driver=None):
    """One customer's outstanding invoices for the SPA drill-down, optionally scoped to
    a single driver's deliveries. Scope is enforced in _outstanding_invoices, so a
    collector only ever sees their own book here even if another customer's id is passed."""
    _require_collection_access()
    invoices = _customer_invoices(frappe.session.user, customer, driver=driver)
    user = frappe.session.user
    # A collector only ever sees a cheque routed to their own driver; an operator here sees any.
    driver_ids = my_driver_ids(user) if is_collector_only(user) else None
    return {
        "customer": customer,
        "customer_name": invoices[0].customer_name if invoices else customer,
        "invoices": invoices,
        "cheque_on_account": _cheque_on_account(customer),
        "cheque_due": open_due_for_customer(customer, driver_ids),
        **_settings_flags(),
        "can_bundle": not is_collector_only(user),
    }


# --- Internal mode (/collect/internal) ------------------------------------------------
# A full-operator tool to prompt ANY customer, ALL payment terms — the opposite of the
# field app's collect-on-delivery scope. Customer-first + lazy: aggregate the customer
# list in one query, then fetch a customer's invoices only when they are opened.

def _require_internal():
    """Internal collection is for operators and sales managers. A scoped actor never belongs
    here — a field collector stays on /collect and a sales user on their own /collect/sales
    book — so the scoped checks come first, before the role set is even consulted."""
    scoped = is_collector_only() or is_sales_only()
    if frappe.session.user == "Guest" or scoped or not (INTERNAL_ROLES & set(frappe.get_roles())):
        frappe.throw("You are not permitted to use internal collection.", frappe.PermissionError)


def _internal_outstanding(customer=None, payment_term=None):
    """All-terms outstanding invoices the internal tool may collect — prepaid and
    actively-bundled invoices dropped (they must never be re-collected, and create_bundle
    rejects them), newest first, optionally scoped to one customer and/or payment term."""
    filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}
    if customer:
        filters["customer"] = customer
    if payment_term:
        filters["payment_terms_template"] = payment_term
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date", "due_date", "payment_terms_template"],
        order_by="posting_date desc",
        limit_page_length=0,
    )
    prepaid = all_prepaid_invoice_names()
    if prepaid:
        invoices = [inv for inv in invoices if inv.name not in prepaid]
    return _drop_bundled(invoices)


def _banner_dues(driver=None, sales_person=None):
    """Flagged cheques for a banner above an unrestricted customer list, under the page's own
    filters. The sales-member filter matches on the customer's book rather than their invoices,
    so a customer flagged with nothing outstanding is still their cheque to collect."""
    dues = all_open_dues(driver)
    if sales_person and dues:
        book = customers_in_book(sales_person)
        dues = [d for d in dues if d.customer in book]
    return dues


def _internal_driver_names():
    """Active drivers who appear on submitted delivery notes — the internal driver filter's
    options (Suspended/Left drivers are excluded). Driver.full_name is the name stored on
    the delivery note."""
    active = set(frappe.get_all("Driver", filters={"status": "Active"}, pluck="full_name"))
    on_dns = frappe.get_all(
        "Delivery Note",
        filters={"docstatus": 1, "driver_name": ["is", "set"]},
        pluck="driver_name",
        distinct=True,
    )
    return sorted(name for name in on_dns if name and name in active)


def _customers_by_latest(invoices):
    """Aggregate invoices into customer rows, newest-invoice customer first — the shape both
    the internal and the sales list return."""
    by_customer = {}
    for inv in invoices:
        row = _accumulate_customer(by_customer, inv)
        if inv.posting_date and (not row.get("latest_date") or inv.posting_date > row["latest_date"]):
            row["latest_date"] = inv.posting_date
    return sorted(
        by_customer.values(), key=lambda r: str(r.get("latest_date") or ""), reverse=True
    )


def _drill_down(invoices, customer, start, page_length, search, cheque_due=None):
    """One customer's invoices for a drill-down: totals over the whole scoped balance, then
    an optionally-searched page of it. Shared by the internal and sales detail views.

    `cheque_due` is the caller's to resolve: scoping here is on invoices, so a caller restricted
    to its own book can be handed a customer outside it and must not leak that customer's cheque."""
    start, page_length = cint(start), cint(page_length) or 50
    total = sum(flt(inv.outstanding_amount) for inv in invoices)
    count = len(invoices)
    if search:
        needle = search.strip().lower()
        invoices = [inv for inv in invoices if needle in inv.name.lower()]

    page = invoices[start : start + page_length]
    _annotate_delivery(page)
    _annotate_customer_phone(page)
    _annotate_sales_person(page)
    _annotate_notes(page)
    _annotate_awaiting_cheque(page)
    return {
        "customer": customer,
        "customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
        "cheque_on_account": _cheque_on_account(customer),
        "cheque_due": cheque_due,
        "invoices": page,
        "invoice_count": count,
        "total_outstanding": total,
        "has_more": start + page_length < len(invoices),
        **_settings_flags(),
    }


def _internal_payment_terms():
    """Distinct payment-terms templates on outstanding invoices — the internal filter's
    options (so a member can view e.g. only NET 30 invoices)."""
    terms = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "outstanding_amount": [">", 0],
            "payment_terms_template": ["is", "set"],
        },
        pluck="payment_terms_template",
        distinct=True,
    )
    return sorted({t for t in terms if t})


@frappe.whitelist()
def internal_customers(driver=None, payment_term=None, sales_person=None):
    """Internal top level: every customer with a COLLECTABLE balance (ALL terms, prepaid
    /actively-bundled excluded), newest-invoice customer first, optionally scoped to one
    driver's deliveries, a payment term and/or a sales team member; the driver, payment-term
    and sales-person options are returned for the filters. Invoices are fetched lazily per
    customer. Excluding prepaid here (via the order-first lookup) keeps a fully-prepaid
    customer from showing a balance that opens to an empty drill-down."""
    _require_internal()
    invoices = scope_to_sales_person(
        _scope_to_driver(_internal_outstanding(payment_term=payment_term), driver), sales_person
    )
    return {
        "customers": _customers_by_latest(invoices),
        "drivers": _internal_driver_names(),
        "payment_terms": _internal_payment_terms(),
        "sales_persons": sales_person_options(),
        # Every flagged cheque, under the same driver and sales-member filters as the list below.
        "cheque_dues": _banner_dues(driver, sales_person),
    }


@frappe.whitelist()
def internal_customer_invoices(customer, start=0, page_length=50, search=None, driver=None, payment_term=None, sales_person=None):
    """One customer's collectable invoices for the internal drill-down: ALL terms
    (prepaid/bundled excluded), newest first, paginated (big accounts hold thousands),
    optionally scoped to one driver's deliveries, a payment term and/or a sales team member.
    The same scoping as the list it drills into, so the totals agree. `search` narrows by
    invoice number; the header totals cover the whole (scoped) balance."""
    _require_internal()
    invoices = scope_to_sales_person(
        _scope_to_driver(_internal_outstanding(customer, payment_term=payment_term), driver),
        sales_person,
    )
    # An operator sees every book, so any flagged cheque for this customer is theirs to see.
    return _drill_down(invoices, customer, start, page_length, search, open_due_for_customer(customer))


# --- Sales mode (/collect/sales) --------------------------------------------------------
# A sales team member's own book: only the customers/invoices their Sales Person is named on,
# across ALL payment terms (they chase receivables, not just collect-on-delivery). Same
# paginated shape as internal mode — one member can own thousands of invoices.

def can_open_sales(user=None):
    """Who may open the sales page: the sales team, and the operators above them. Mirrors
    _require_sales so the SPA routes the same way the API answers."""
    roles = set(frappe.get_roles(user or frappe.session.user))
    return bool((SALES_MANAGER_ROLES | {SALES_ROLE}) & roles)


def _require_sales():
    """The sales page is for the sales team and the managers above them."""
    if frappe.session.user == "Guest" or not can_open_sales():
        frappe.throw("Sales collection is for the sales team.", frappe.PermissionError)


def _own_book_only():
    """True when the caller may only see the book of their own Sales Person: a sales user
    always, and their sales manager too while iPay Settings restricts managers. An iPay
    operator is never gated — the setting is about the sales team, not about them."""
    if OPERATOR_ROLES & set(frappe.get_roles()):
        return False
    return is_sales_only() or bool(
        frappe.db.get_single_value("iPay Settings", "restrict_sales_managers")
    )


def _sales_view_person(sales_person):
    """The Sales Person to scope the sales page to. Locked to the caller's own for anyone on
    their own book — the caller-supplied value is ignored, so it can never widen their view.
    An unrestricted manager sees every book (None) or filters to the one they picked."""
    if _own_book_only():
        return my_sales_person()
    return sales_person or None


def _sales_cheque_dues(own_book, person):
    """Flagged cheques for the sales banner, scoped exactly like the customer list beneath it:
    one member's book when locked to it or filtered to a member, every book for an unrestricted
    manager who has picked nobody.

    Matched on book membership, not can_access_customer: that asks for an outstanding invoice,
    which would drop the flagged customer whose cheque is the last thing owed."""
    if person:
        return open_dues_for_customers(customers_in_book(person))
    return [] if own_book else all_open_dues()


@frappe.whitelist()
def sales_customers(payment_term=None, sales_person=None):
    """Customers with a collectable balance for the sales page, newest-invoice customer first,
    optionally scoped to a payment term. A sales user gets their OWN book (resolved from their
    login); their manager gets every member's book and may filter to one, unless the settings
    restrict managers. An unmapped login reports `unmapped` so the page can say why it is empty."""
    _require_sales()
    own_book = _own_book_only()
    person = _sales_view_person(sales_person)
    if own_book and not person:
        return {
            "customers": [], "payment_terms": [], "sales_persons": [],
            "sales_person": "", "is_manager": False, "unmapped": True,
        }
    invoices = scope_to_sales_person(_internal_outstanding(payment_term=payment_term), person)
    return {
        "customers": _customers_by_latest(invoices),
        "payment_terms": _internal_payment_terms(),
        # Only someone who may see other books gets the filter; a locked caller never does.
        "sales_persons": [] if own_book else sales_person_options(),
        "sales_person": person or "",
        "is_manager": not own_book,
        # Flagged cheques for awareness, under the same book/member scope as the list.
        "cheque_dues": _sales_cheque_dues(own_book, person),
        "unmapped": False,
    }


@frappe.whitelist()
def sales_customer_invoices(customer, start=0, page_length=50, search=None, payment_term=None, sales_person=None):
    """One customer drilled down, scoped exactly like sales_customers — so a caller on their
    own book who passes someone else's customer gets nothing rather than that balance."""
    _require_sales()
    if _own_book_only() and not my_sales_person():
        frappe.throw("Your login is not linked to a sales person.", frappe.PermissionError)
    invoices = scope_to_sales_person(
        _internal_outstanding(customer, payment_term=payment_term),
        _sales_view_person(sales_person),
    )
    # Book membership, the same test the list banner uses — can_access_customer would deny the
    # drill-down the very cheque the banner just linked the member to.
    person = _sales_view_person(sales_person)
    due = open_due_for_customer(customer)
    if person and customer not in customers_in_book(person):
        due = None
    return _drill_down(invoices, customer, start, page_length, search, due)

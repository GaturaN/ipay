import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime, today

from ipay.ipay.main.utils.prepaid import all_prepaid_invoice_names, prepaid_invoice_names
from ipay.ipay.main.utils.collector import OPERATOR_ROLES, collector_scope, is_collector_only
from ipay.ipay.main.utils.constants import ACTIVE_BUNDLE_WINDOW_MIN
from ipay.ipay.main.utils.sales import (
    SALES_ROLE,
    is_sales_only,
    my_sales_person,
    sales_person_options,
    scope_to_sales_person,
)

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User", "iPay Collector"}
# Who may load the SPA shell. A sales member is deliberately NOT in ALLOWED_ROLES: that set
# gates the field endpoints, which scope by collector and would hand a sales member the whole
# collect-on-delivery book. They reach their own data through the sales endpoints below.
PAGE_ROLES = ALLOWED_ROLES | {SALES_ROLE}


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


def _require_collection_access():
    """Operators and collectors only. Guests are redirected to login by callers."""
    if frappe.session.user == "Guest" or not (ALLOWED_ROLES & set(frappe.get_roles())):
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
    so every outstanding invoice is collectable (behaviour before the setting existed)."""
    settings = frappe.get_cached_doc("iPay Settings")
    return [row.payment_terms_template for row in (settings.get("collect_payment_terms") or [])]


def _settings_flags():
    """The two iPay Settings every collection response carries: hosted-checkout
    availability and the M-Pesa STK ceiling."""
    return {
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
        "mpesa_max": flt(frappe.db.get_single_value("iPay Settings", "mpesa_max_amount")),
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
    on-file phone). Optionally scoped to a single driver's deliveries."""
    invoices = _outstanding_invoices(user, customer)
    _annotate_delivery(invoices)
    if driver:
        invoices = [inv for inv in invoices if driver in (inv.get("drivers") or [])]
    _annotate_customer_phone(invoices)
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
    if is_sales_only(user):
        frappe.local.flags.redirect_location = "/collect/sales"
        raise frappe.Redirect
    _require_collection_access()
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
    _require_collection_access()

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
    }


@frappe.whitelist()
def customer_collection(customer, driver=None):
    """One customer's outstanding invoices for the SPA drill-down, optionally scoped to
    a single driver's deliveries. Scope is enforced in _outstanding_invoices, so a
    collector only ever sees their own book here even if another customer's id is passed."""
    _require_collection_access()
    invoices = _customer_invoices(frappe.session.user, customer, driver=driver)
    return {
        "customer": customer,
        "customer_name": invoices[0].customer_name if invoices else customer,
        "invoices": invoices,
        **_settings_flags(),
        "can_bundle": not is_collector_only(frappe.session.user),
    }


# --- Internal mode (/collect/internal) ------------------------------------------------
# A full-operator tool to prompt ANY customer, ALL payment terms — the opposite of the
# field app's collect-on-delivery scope. Customer-first + lazy: aggregate the customer
# list in one query, then fetch a customer's invoices only when they are opened.

def _require_internal():
    """Internal collection is for full operators only — a field collector stays on the
    scoped /collect app."""
    if frappe.session.user == "Guest" or not (OPERATOR_ROLES & set(frappe.get_roles())):
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


def _drill_down(invoices, customer, start, page_length, search):
    """One customer's invoices for a drill-down: totals over the whole scoped balance, then
    an optionally-searched page of it. Shared by the internal and sales detail views."""
    start, page_length = cint(start), cint(page_length) or 50
    total = sum(flt(inv.outstanding_amount) for inv in invoices)
    count = len(invoices)
    if search:
        needle = search.strip().lower()
        invoices = [inv for inv in invoices if needle in inv.name.lower()]

    page = invoices[start : start + page_length]
    _annotate_delivery(page)
    _annotate_customer_phone(page)
    return {
        "customer": customer,
        "customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
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
    return _drill_down(invoices, customer, start, page_length, search)


# --- Sales mode (/collect/sales) --------------------------------------------------------
# A sales team member's own book: only the customers/invoices their Sales Person is named on,
# across ALL payment terms (they chase receivables, not just collect-on-delivery). Same
# paginated shape as internal mode — one member can own thousands of invoices.

def _require_sales():
    """The sales page is for sales members; operators may open it too (it always shows the
    caller's OWN book, so an operator without a Sales Person simply sees nothing)."""
    if frappe.session.user == "Guest" or not (
        (OPERATOR_ROLES | {SALES_ROLE}) & set(frappe.get_roles())
    ):
        frappe.throw("You are not permitted to use sales collection.", frappe.PermissionError)


@frappe.whitelist()
def sales_customers(payment_term=None):
    """The signed-in sales member's own customers with a collectable balance, newest-invoice
    customer first, optionally scoped to a payment term. `sales_person` is never taken from
    the caller — it is resolved from their login, so this can only ever return their own book.
    An unmapped login reports `unmapped` so the page can say why it is empty."""
    _require_sales()
    person = my_sales_person()
    if not person:
        return {"customers": [], "payment_terms": [], "sales_person": "", "unmapped": True}
    invoices = scope_to_sales_person(_internal_outstanding(payment_term=payment_term), person)
    return {
        "customers": _customers_by_latest(invoices),
        "payment_terms": _internal_payment_terms(),
        "sales_person": person,
        "unmapped": False,
    }


@frappe.whitelist()
def sales_customer_invoices(customer, start=0, page_length=50, search=None, payment_term=None):
    """One of the signed-in sales member's customers, drilled down. Scoped to their own book
    exactly like sales_customers, so passing another member's customer returns nothing rather
    than that customer's balance."""
    _require_sales()
    person = my_sales_person()
    if not person:
        frappe.throw("Your login is not linked to a sales person.", frappe.PermissionError)
    invoices = scope_to_sales_person(
        _internal_outstanding(customer, payment_term=payment_term), person
    )
    return _drill_down(invoices, customer, start, page_length, search)

import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime, today

from ipay.ipay.main.utils.prepaid import prepaid_invoice_names
from ipay.ipay.main.utils.collector import is_collector_only, collector_scope
from ipay.ipay.main.utils.constants import ACTIVE_BUNDLE_WINDOW_MIN

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User", "iPay Collector"}


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
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date", "due_date"],
        order_by="posting_date asc",
        limit_page_length=0,
    )
    prepaid = prepaid_invoice_names([inv.name for inv in invoices])
    if prepaid:
        invoices = [inv for inv in invoices if inv.name not in prepaid]
    return _drop_bundled(invoices)


def _group_customers(invoices):
    """Group outstanding invoices by customer — total owed, invoice count, and search
    keywords (each invoice's number and delivery note, so the list can be searched by
    either) — most-owed first. Invoices must already be delivery-annotated."""
    by_customer = {}
    for inv in invoices:
        row = by_customer.get(inv.customer)
        if row is None:
            row = by_customer[inv.customer] = {
                "customer": inv.customer,
                "customer_name": inv.customer_name or inv.customer,
                "total_outstanding": 0.0,
                "invoice_count": 0,
                "keywords": [],
            }
        row["total_outstanding"] += flt(inv.outstanding_amount)
        row["invoice_count"] += 1
        row["keywords"].append(inv.name)
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
    scoped app (/collect); guests log in first."""
    context.no_cache = 1
    if frappe.session.user == "Guest":
        # Back to this route (not straight to /collect/internal) so the role branch below
        # runs after login — a collector must land on /collect, not internal mode.
        frappe.local.flags.redirect_location = "/login?redirect-to=/collect_payments"
        raise frappe.Redirect
    _require_collection_access()
    frappe.local.flags.redirect_location = (
        "/collect" if is_collector_only(frappe.session.user) else "/collect/internal"
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
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
        "can_bundle": not is_collector_only(frappe.session.user),
    }


# --- Internal mode (/collect/internal) ------------------------------------------------
# A full-operator tool to prompt ANY customer, ALL payment terms — the opposite of the
# field app's collect-on-delivery scope. Customer-first + lazy: aggregate the customer
# list in one query, then fetch a customer's invoices only when they are opened.

INTERNAL_ROLES = {"System Manager", "iPay Manager", "iPay User"}


def _require_internal():
    """Internal collection is for full operators only — a field collector stays on the
    scoped /collect app."""
    if frappe.session.user == "Guest" or not (INTERNAL_ROLES & set(frappe.get_roles())):
        frappe.throw("You are not permitted to use internal collection.", frappe.PermissionError)


@frappe.whitelist()
def internal_customers():
    """Internal top level: every customer with an outstanding balance (ALL terms),
    newest-invoice customer first. One aggregate query — the invoices themselves are
    fetched lazily per customer, so nothing heavy loads upfront."""
    _require_internal()
    customers = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]},
        fields=[
            "customer",
            "max(customer_name) as customer_name",
            "sum(outstanding_amount) as total_outstanding",
            "count(name) as invoice_count",
            "max(posting_date) as latest_date",
        ],
        group_by="customer",
        order_by="latest_date desc",
    )
    return {"customers": customers}


@frappe.whitelist()
def internal_customer_invoices(customer, start=0, page_length=50, search=None):
    """One customer's outstanding invoices for the internal drill-down: ALL terms,
    newest first, paginated (big accounts hold thousands). `search` narrows by invoice
    number within the customer; the header totals still cover the whole balance."""
    _require_internal()
    start, page_length = cint(start), cint(page_length) or 50

    base = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0], "customer": customer}
    totals = frappe.get_all(
        "Sales Invoice",
        filters=base,
        fields=["sum(outstanding_amount) as total", "count(name) as cnt"],
    )[0]

    page_filters = dict(base)
    if search:
        page_filters["name"] = ["like", f"%{search}%"]
    # No search means page_filters == base, so reuse the count already taken above.
    matched = frappe.db.count("Sales Invoice", page_filters) if search else cint(totals.cnt)
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=page_filters,
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date", "due_date"],
        order_by="posting_date desc",
        limit_start=start,
        limit_page_length=page_length,
    )
    _annotate_delivery(invoices)
    _annotate_customer_phone(invoices)
    return {
        "customer": customer,
        "customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
        "invoices": invoices,
        "invoice_count": cint(totals.cnt),
        "total_outstanding": flt(totals.total),
        "has_more": start + page_length < matched,
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
    }

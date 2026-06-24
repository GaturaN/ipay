import frappe
from frappe.utils import flt, today

from ipay.ipay.main.utils.prepaid import prepaid_invoice_names
from ipay.ipay.main.utils.collector import is_collector_only, collector_scope

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User", "iPay Collector"}


def _drop_bundled(invoices):
    """Remove invoices that are members of a submitted bundle (iPay Request
    Invoice rows under a docstatus=1 request) — they're collected via the bundle."""
    if not invoices:
        return invoices
    rows = frappe.get_all(
        "iPay Request Invoice",
        filters={"sales_invoice": ["in", [inv.name for inv in invoices]]},
        fields=["sales_invoice", "parent"],
    )
    if not rows:
        return invoices
    submitted = set(frappe.get_all(
        "iPay Request",
        filters={"name": ["in", list({r.parent for r in rows})], "docstatus": 1},
        pluck="name",
    ))
    bundled = {r.sales_invoice for r in rows if r.parent in submitted}
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
        inv.driver_filter = "|".join(inv.drivers)  # pipe-joined for the Jinja data-attr


def _collection_invoices(user):
    """The outstanding Sales Invoices `user` may collect: prepaid and
    already-bundled invoices dropped, each annotated with its delivery note(s)
    and driver(s). Returns (invoices, drivers) — the list and the sorted distinct
    driver names present. A collector sees only their own work; full operators
    see everything. Shared by the Jinja page (get_context) and the SPA API
    (collection_list)."""
    collector = is_collector_only(user)
    si_filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}
    if collector:
        si_filters["name"] = ["in", list(collector_scope(user)["invoices"]) or ["__none__"]]

    invoices = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date"],
        order_by="posting_date desc",
        limit_page_length=100,
    )

    prepaid = prepaid_invoice_names([inv.name for inv in invoices])
    if prepaid:
        invoices = [inv for inv in invoices if inv.name not in prepaid]
    invoices = _drop_bundled(invoices)
    _annotate_delivery(invoices)
    _annotate_customer_phone(invoices)

    drivers = sorted({d for inv in invoices for d in inv.get("drivers", [])})
    return invoices, drivers


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
    context.no_cache = 1
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/collect_payments"
        raise frappe.Redirect
    _require_collection_access()

    invoices, drivers = _collection_invoices(frappe.session.user)
    context.invoices = invoices
    context.drivers = drivers
    context.enable_redirect = frappe.db.get_single_value("iPay Settings", "enable_redirect")

    stats = collection_stats()
    context.collected_today = stats["collected_today"]
    context.outstanding_today = stats["outstanding_today"]


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
def collection_stats(driver=None):
    """Today's collected + yet-to-collect totals, optionally scoped to a single
    driver (by name) — backs the driver filter on the collection page. Operator/
    collector gated; a collector is always restricted to their own book, so the
    driver argument can only narrow within it, never widen it."""
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
    if invoices is not None:
        out_filter["name"] = ["in", list(invoices) or ["__none__"]]
    outstanding_today = _sum_outstanding(out_filter)

    return {"collected_today": collected_today, "outstanding_today": outstanding_today}


@frappe.whitelist()
def collection_list():
    """Data for the iPay Collect SPA: the outstanding invoices the caller may
    collect (prepaid/bundled dropped, delivery + driver annotated), the distinct
    drivers present, and whether hosted checkout is enabled. The Jinja page builds
    the same data via get_context, so both share `_collection_invoices`."""
    _require_collection_access()
    invoices, drivers = _collection_invoices(frappe.session.user)
    return {
        "invoices": invoices,
        "drivers": drivers,
        "enable_redirect": bool(frappe.db.get_single_value("iPay Settings", "enable_redirect")),
    }

"""Visibility scoping for the iPay Collector role.

A collector is a delivery person who may prompt/collect payment only for their
own work. "Their work" is the union of two signals (per product decision):

  * Driver-based — invoices delivered by one of their drivers
    (Delivery Note.driver -> Driver.user == the collector's login).
  * Explicit assignment — iPay Requests assigned to them via Frappe's native
    "Assign To" (the _assign field).

Full operators (System Manager / iPay Manager / iPay User) are never scoped.
Everything degrades safely: with no driver mapping and no assignment, a
collector simply sees nothing rather than everything.
"""

import frappe

COLLECTOR_ROLE = "iPay Collector"
OPERATOR_ROLES = {"System Manager", "iPay Manager", "iPay User"}


def is_collector_only(user=None):
    """True when the user is a collector and NOT a full operator (so their view
    must be scoped). Full operators short-circuit every check to unrestricted."""
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    return COLLECTOR_ROLE in roles and not (OPERATOR_ROLES & roles)


def my_driver_ids(user=None):
    """Driver records mapped to this user via the Driver.user link."""
    user = user or frappe.session.user
    if not frappe.get_meta("Driver").has_field("user"):
        return []
    return frappe.get_all("Driver", filters={"user": user}, pluck="name")


def _assign_like(user):
    # _assign stores a JSON array of user ids, e.g. ["a@x.com"].
    return ["like", f'%"{user}"%']


def my_assigned_requests(user=None):
    """iPay Requests explicitly assigned to this user (native _assign)."""
    user = user or frappe.session.user
    return frappe.get_all("iPay Request", filters={"_assign": _assign_like(user)}, pluck="name")


def _invoices_delivered_by(drivers):
    """Sales Invoices whose delivery note's driver is one of `drivers`."""
    if not drivers:
        return set()
    dns = frappe.get_all(
        "Delivery Note", filters={"driver": ["in", drivers], "docstatus": 1}, pluck="name"
    )
    if not dns:
        return set()
    return set(frappe.get_all(
        "Sales Invoice Item", filters={"delivery_note": ["in", dns]}, pluck="parent"
    ))


def collector_scope(user=None):
    """The set of Sales Invoices and iPay Requests a collector may see, cached for the life of
    the request — access is checked once per invoice in a bundle, and the scope is several
    unbounded reads (mirrors sales._cached_scope).

    invoices = driver-delivered ∪ assigned-request invoices (single + bundle).
    requests = explicitly-assigned ∪ requests covering a driver-delivered invoice.
    """
    user = user or frappe.session.user
    cache = getattr(frappe.local, "ipay_collector_scope", None)
    if cache is None:
        cache = frappe.local.ipay_collector_scope = {}
    if user not in cache:
        cache[user] = _compute_collector_scope(user)
    return cache[user]


def _compute_collector_scope(user):
    invoices = _invoices_delivered_by(my_driver_ids(user))
    requests = set(my_assigned_requests(user))

    if requests:
        invoices.update(frappe.get_all(
            "iPay Request", filters={"name": ["in", list(requests)]}, pluck="sales_invoice"
        ))
        invoices.update(frappe.get_all(
            "iPay Request Invoice", filters={"parent": ["in", list(requests)]}, pluck="sales_invoice"
        ))

    if invoices:
        requests.update(frappe.get_all(
            "iPay Request", filters={"sales_invoice": ["in", list(invoices)]}, pluck="name"
        ))

    invoices.discard(None)
    requests.discard(None)
    return {"invoices": invoices, "requests": requests}


def can_access_invoice(sales_invoice, user=None):
    """May this user prompt/collect for the given invoice? Always True for a full operator;
    a scoped actor (collector and/or sales member) may act only on their own work — the
    union of the scopes their roles grant, so holding both roles widens rather than narrows."""
    from ipay.ipay.main.utils import sales

    user = user or frappe.session.user
    scoped = False
    if is_collector_only(user):
        scoped = True
        if sales_invoice and sales_invoice in collector_scope(user)["invoices"]:
            return True
    if sales.is_sales_only(user):
        scoped = True
        if sales.can_access_invoice(sales_invoice, user):
            return True
    return not scoped


def can_access_customer(customer, user=None):
    """May this user act on a customer-level (on-account) cheque? Always True for a full operator;
    a scoped actor must hold at least one of the customer's outstanding invoices. Checked against
    the actor's own (bounded) book in one query — never by scanning the customer's every invoice,
    which for a large customer was minutes of work per request."""
    from ipay.ipay.main.utils import sales

    user = user or frappe.session.user
    scoped = False
    if is_collector_only(user):
        scoped = True
        if _customer_has_scoped_invoice(customer, collector_scope(user)["invoices"]):
            return True
    if sales.is_sales_only(user):
        scoped = True
        if sales.can_access_customer(customer, user):
            return True
    if scoped:
        return False
    # Unscoped (full operator / Sales Manager): the old loop granted only when the customer had
    # an outstanding invoice to grant on, so keep that — an on-account cheque still needs one.
    return _customer_has_outstanding(customer)


def _customer_has_outstanding(customer):
    """True when the customer has any outstanding invoice at all."""
    return bool(
        frappe.db.exists(
            "Sales Invoice",
            {"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        )
    )


def _customer_has_scoped_invoice(customer, scope_invoices):
    """True when one of `scope_invoices` is an outstanding invoice of `customer` — the same
    accept test the per-invoice check applied, intersected in the database in one query."""
    return bool(scope_invoices) and bool(
        frappe.db.exists(
            "Sales Invoice",
            {
                "name": ["in", list(scope_invoices)],
                "customer": customer,
                "docstatus": 1,
                "outstanding_amount": [">", 0],
            },
        )
    )


def can_access_request(request_name, user=None):
    """May this user act on the given iPay Request? Always True for a full operator; for a
    scoped actor, only their own requests — and for a bundle, only when EVERY member invoice
    is their own work (owning one member must not grant prompting the whole bundle across
    co-invoices)."""
    from ipay.ipay.main.utils import sales

    user = user or frappe.session.user
    scoped = False
    if is_collector_only(user):
        scoped = True
        if request_name and _collector_owns_request(request_name, user):
            return True
    if sales.is_sales_only(user):
        scoped = True
        if sales.can_access_request(request_name, user):
            return True
    return not scoped


def _collector_owns_request(request_name, user):
    """Every invoice a request covers must be the collector's own work."""
    scope = collector_scope(user)
    if request_name not in scope["requests"]:
        return False
    members = frappe.get_all(
        "iPay Request Invoice", filters={"parent": request_name}, pluck="sales_invoice"
    )
    return all(inv in scope["invoices"] for inv in members if inv)

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
    """The set of Sales Invoices and iPay Requests a collector may see.

    invoices = driver-delivered ∪ assigned-request invoices (single + bundle).
    requests = explicitly-assigned ∪ requests covering a driver-delivered invoice.
    """
    user = user or frappe.session.user
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
    """May this user prompt/collect for the given invoice? Always True for full
    operators; for a collector, only their own work."""
    user = user or frappe.session.user
    if not is_collector_only(user):
        return True
    if not sales_invoice:
        return False
    return sales_invoice in collector_scope(user)["invoices"]


def can_access_request(request_name, user=None):
    """May this user act on the given iPay Request? Always True for full
    operators; for a collector, only their assigned/driver-mapped requests."""
    user = user or frappe.session.user
    if not is_collector_only(user):
        return True
    if not request_name:
        return False
    return request_name in collector_scope(user)["requests"]

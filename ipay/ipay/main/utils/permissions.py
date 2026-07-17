"""Desk row-level scoping for iPay Request (a scoped actor sees only their own work).

These hooks apply to frappe.get_list, list views and reports. They do NOT apply
to the collect_payments page (it builds its own query and scopes itself) nor to
frappe.get_all.
"""

import frappe

from ipay.ipay.main.utils.collector import is_collector_only, my_driver_ids
from ipay.ipay.main.utils.sales import is_sales_only, my_sales_person


def _collector_conditions(user):
    """A collector's work: requests assigned to them (_assign) OR delivered by their drivers."""
    conditions = [
        "`tabiPay Request`._assign like {0}".format(frappe.db.escape('%"' + user + '"%'))
    ]
    drivers = my_driver_ids(user)
    if drivers:
        driver_list = ", ".join(frappe.db.escape(d) for d in drivers)
        conditions.append(
            "`tabiPay Request`.sales_invoice in ("
            "select sii.parent from `tabSales Invoice Item` sii "
            "join `tabDelivery Note` dn on dn.name = sii.delivery_note "
            "where dn.driver in ({0}))".format(driver_list)
        )
    return conditions


def _sales_conditions(user):
    """A sales member's book: requests for an invoice their Sales Person is named on, or for
    a customer their Sales Person is named on — the same union the collect page scopes by."""
    person = my_sales_person(user)
    if not person:
        return []
    named = frappe.db.escape(person)
    return [
        "`tabiPay Request`.sales_invoice in (select st.parent from `tabSales Team` st "
        "where st.parenttype = 'Sales Invoice' and st.sales_person = {0})".format(named),
        "`tabiPay Request`.customer in (select st.parent from `tabSales Team` st "
        "where st.parenttype = 'Customer' and st.sales_person = {0})".format(named),
    ]


def ipay_request_query_conditions(user=None):
    """SQL WHERE fragment limiting the iPay Request list to a scoped actor's own work — the
    union of the scopes their roles grant. An unscoped user (operator/manager) gets no
    fragment; a scoped actor we cannot map gets a false one, so they see nothing rather than
    everything."""
    user = user or frappe.session.user
    collector, sales = is_collector_only(user), is_sales_only(user)
    if not (collector or sales):
        return ""

    conditions = []
    if collector:
        conditions.extend(_collector_conditions(user))
    if sales:
        conditions.extend(_sales_conditions(user))
    if not conditions:
        return "1 = 0"
    return "(" + " or ".join(conditions) + ")"


def ipay_request_has_permission(doc, ptype=None, user=None, **kwargs):
    """Single-document check mirroring the list scoping above. Frappe also calls
    this at the doctype level (doc is None / a string) and passes extra kwargs
    (e.g. debug); allow those — row scoping is handled per-doc and by the query
    conditions."""
    user = user or frappe.session.user
    if not (is_collector_only(user) or is_sales_only(user)):
        return True
    if not doc or isinstance(doc, str):
        return True
    from ipay.ipay.main.utils.collector import can_access_request

    return can_access_request(doc.name, user)

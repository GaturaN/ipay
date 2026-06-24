"""Desk row-level scoping for iPay Request (collectors see only their own).

These hooks apply to frappe.get_list, list views and reports. They do NOT apply
to the collect_payments page (it builds its own query and scopes itself) nor to
frappe.get_all.
"""

import frappe

from ipay.ipay.main.utils.collector import is_collector_only, my_driver_ids


def ipay_request_query_conditions(user=None):
    """SQL WHERE fragment limiting the iPay Request list to a collector's work:
    requests assigned to them (_assign) OR delivered by one of their drivers."""
    user = user or frappe.session.user
    if not is_collector_only(user):
        return ""

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
    return "(" + " or ".join(conditions) + ")"


def ipay_request_has_permission(doc, ptype=None, user=None, **kwargs):
    """Single-document check mirroring the list scoping above. Frappe also calls
    this at the doctype level (doc is None / a string) and passes extra kwargs
    (e.g. debug); allow those — row scoping is handled per-doc and by the query
    conditions."""
    user = user or frappe.session.user
    if not is_collector_only(user):
        return True
    if not doc or isinstance(doc, str):
        return True
    from ipay.ipay.main.utils.collector import can_access_request

    return can_access_request(doc.name, user)

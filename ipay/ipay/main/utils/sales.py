"""Visibility scoping for the sales team, on ERPNext's own Sales roles.

A Sales User may prompt/collect only for their own book: the customers and the invoices
their Sales Person record is named on. The login is mapped to a Sales Person through
ERPNext's own chain — Employee.user_id -> Sales Person.employee.

Anyone above them — a Sales Manager or an iPay operator — uses the internal page instead,
which already lists every customer and filters by sales person.

Everything degrades safely, mirroring collector.py: a login with no Employee, or an
Employee with no Sales Person, resolves to nothing and therefore sees nothing rather than
everything.
"""

import frappe

from ipay.ipay.main.utils.collector import OPERATOR_ROLES

SALES_ROLE = "Sales User"
SALES_MANAGER_ROLES = OPERATOR_ROLES | {"Sales Manager"}


def is_sales_only(user=None):
    """True when the user collects their own sales book (so their view must be scoped): they
    sell and rank no higher. Mirrors is_collector_only — a manager role cancels the scoping,
    so a Sales User who is also a Sales Manager sees everything via the internal page."""
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    return SALES_ROLE in roles and not (SALES_MANAGER_ROLES & roles)


def my_sales_person(user=None):
    """The Sales Person this login is, via ERPNext's Employee.user_id link, or None when
    that chain is unset. Group nodes are never a person — scoping matches a name exactly,
    so a group would resolve to only the work booked on the group itself."""
    user = user or frappe.session.user
    if not user or user == "Guest":
        return None
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        return None
    return frappe.db.get_value(
        "Sales Person", {"employee": employee, "is_group": 0}, "name"
    )


def sales_person_scope(sales_person):
    """The invoices and the customers a sales team member is named on, read from the live
    Sales Team rows of each."""
    invoices = set(frappe.get_all(
        "Sales Team",
        filters={"parenttype": "Sales Invoice", "sales_person": sales_person},
        pluck="parent",
    ))
    customers = set(frappe.get_all(
        "Sales Team",
        filters={"parenttype": "Customer", "sales_person": sales_person},
        pluck="parent",
    ))
    return invoices, customers


def scope_to_sales_person(invoices, sales_person):
    """Keep only invoices assigned to the named sales team member — by the invoice's own
    sales team, or by their customer's. ERPNext copies the customer's team onto an invoice
    when it is created and never refreshes it, so a reassigned customer's older invoices
    keep the previous member; matching either honours both readings. A post-filter, like
    _scope_to_driver, so it composes with the other filters."""
    if not sales_person:
        return invoices
    named, customers = sales_person_scope(sales_person)
    return [inv for inv in invoices if inv.name in named or inv.customer in customers]


def sales_person_options():
    """Sales team members named on any customer or invoice — the internal filter's options.
    Read from the live Sales Team rows rather than the Sales Person master so a member whose
    master record was deleted (their assignments survive) can still be filtered on, and a
    disabled member's outstanding work stays reachable."""
    names = frappe.get_all(
        "Sales Team",
        filters={"parenttype": ["in", ["Customer", "Sales Invoice"]]},
        pluck="sales_person",
        distinct=True,
    )
    # Drop tree group nodes (e.g. the "Sales Team" root, which some rows are booked against):
    # the scope matches a name exactly, so a group would report only what is booked on the
    # group itself and never its members' work — a total that reads as the whole team's.
    groups = set(frappe.get_all("Sales Person", filters={"is_group": 1}, pluck="name"))
    return sorted({name for name in names if name and name not in groups})


def _cached_scope(sales_person):
    """The member's book, cached for the life of the request: create_bundle checks access
    once per invoice and the scope is two unbounded reads."""
    cache = getattr(frappe.local, "ipay_sales_scope", None)
    if cache is None:
        cache = frappe.local.ipay_sales_scope = {}
    if sales_person not in cache:
        cache[sales_person] = sales_person_scope(sales_person)
    return cache[sales_person]


def customers_in_book(sales_person):
    """Every customer in a member's book: those they are named on, plus the customers of the
    invoices they are named on — the same either/or reading as scope_to_sales_person.

    Unlike can_access_customer this asks for no outstanding invoice: a flagged cheque may be the
    only thing left on a customer, and that is exactly the one their banner must still show."""
    named, customers = _cached_scope(sales_person)
    if not named:
        return set(customers)
    # Submitted only: a Sales Team row survives on a draft or cancelled invoice, and counting
    # those would put customers in the book that the customer list can never show.
    return set(customers) | set(frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", list(named)], "docstatus": 1},
        pluck="customer",
        distinct=True,
    ))


def _in_book(sales_invoice, named, customers):
    """True when the invoice is in a book described by (named invoices, named customers)."""
    if not sales_invoice:
        return False
    if sales_invoice in named:
        return True
    customer = frappe.db.get_value("Sales Invoice", sales_invoice, "customer")
    return bool(customer) and customer in customers


def can_access_invoice(sales_invoice, user=None):
    """May this sales member prompt/collect for the given invoice? Only their own book."""
    person = my_sales_person(user)
    if not person:
        return False
    named, customers = _cached_scope(person)
    return _in_book(sales_invoice, named, customers)


def can_access_customer(customer, user=None):
    """May this sales member act on a customer-level (on-account) cheque? Only a customer with an
    outstanding invoice in their book — the customer is theirs, or one of their named invoices is
    the customer's. One query either way; never a scan of the customer's every invoice."""
    person = my_sales_person(user)
    if not person:
        return False
    named, customers = _cached_scope(person)
    if customer in customers:
        return bool(frappe.db.exists(
            "Sales Invoice",
            {"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        ))
    return bool(named) and bool(frappe.db.exists(
        "Sales Invoice",
        {"name": ["in", list(named)], "customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
    ))


def can_access_request(request_name, user=None):
    """May this sales member act on the given iPay Request? Only when EVERY invoice it
    covers is their own book — owning one member must not grant prompting a bundle across
    another member's invoices (mirrors collector.can_access_request)."""
    person = my_sales_person(user)
    if not person or not request_name:
        return False
    members = [frappe.db.get_value("iPay Request", request_name, "sales_invoice")]
    members += frappe.get_all(
        "iPay Request Invoice", filters={"parent": request_name}, pluck="sales_invoice"
    )
    members = [inv for inv in members if inv]
    if not members:
        return False
    named, customers = _cached_scope(person)
    return all(_in_book(inv, named, customers) for inv in members)

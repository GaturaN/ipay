import frappe
from frappe.utils import flt, today

from ipay.ipay.main.utils.prepaid import prepaid_invoice_names

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User"}


def _sum_outstanding(extra_filters=None):
    """Sum of outstanding on submitted, non-return, unpaid Sales Invoices."""
    filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}
    if extra_filters:
        filters.update(extra_filters)
    rows = frappe.get_all("Sales Invoice", filters=filters, fields=["sum(outstanding_amount) as total"])
    return flt(rows[0].total) if rows else 0


def _collected_totals(today_date):
    """Collected via iPay = paid_amount of Payment Entries linked from iPay
    Requests. Returns (overall, today)."""
    row = frappe.db.sql(
        """
        select
            coalesce(sum(pe.paid_amount), 0) as total,
            coalesce(sum(case when pe.posting_date = %(today)s then pe.paid_amount else 0 end), 0) as today_total
        from `tabPayment Entry` pe
        inner join `tabiPay Request` ir on ir.payment_entry = pe.name
        where pe.docstatus = 1
        """,
        {"today": today_date},
        as_dict=True,
    )
    return (flt(row[0].total), flt(row[0].today_total)) if row else (0, 0)


def get_context(context):
    context.no_cache = 1

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/collect_payments"
        raise frappe.Redirect

    if not (ALLOWED_ROLES & set(frappe.get_roles())):
        frappe.throw("You are not permitted to collect payments.", frappe.PermissionError)

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "customer_name", "outstanding_amount", "posting_date"],
        order_by="posting_date desc",
        limit_page_length=100,
    )

    # Prepaid invoices settle automatically and must never be collected here, so
    # drop them from the list (no row, no link, no prompt).
    prepaid = prepaid_invoice_names([inv.name for inv in invoices])
    if prepaid:
        invoices = [inv for inv in invoices if inv.name not in prepaid]

    # Attach the delivery note(s) linked to each invoice (one batched query).
    if invoices:
        names = [inv.name for inv in invoices]
        links = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": ["in", names], "delivery_note": ["is", "set"]},
            fields=["parent", "delivery_note"],
        )
        dn_map = {}
        for link in links:
            dn_map.setdefault(link.parent, set()).add(link.delivery_note)

        # Resolve each delivery note's driver (one batched query) so invoices can
        # be filtered by driver on the page. The driver lives on the Delivery
        # Note, not the Sales Invoice.
        dn_names = {n for names_set in dn_map.values() for n in names_set}
        driver_by_dn = {}
        if dn_names:
            for dn in frappe.get_all(
                "Delivery Note",
                filters={"name": ["in", list(dn_names)]},
                fields=["name", "driver_name"],
            ):
                driver_by_dn[dn.name] = dn.driver_name or ""

        for inv in invoices:
            dns = sorted(dn_map.get(inv.name, []))
            inv.delivery_note = ", ".join(dns)
            inv.driver_name = next((driver_by_dn[n] for n in dns if driver_by_dn.get(n)), "")

    context.invoices = invoices
    context.drivers = sorted({inv.driver_name for inv in invoices if getattr(inv, "driver_name", "")})
    context.enable_redirect = frappe.db.get_single_value("iPay Settings", "enable_redirect")

    # Collection totals: collected via iPay vs still outstanding, today and overall.
    today_date = today()
    context.collected_total, context.collected_today = _collected_totals(today_date)
    context.outstanding_total = _sum_outstanding()
    context.outstanding_today = _sum_outstanding({"posting_date": today_date})

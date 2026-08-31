import frappe


def get_context(context):
    context.no_cache = 1
    context.favicon = "/assets/ipay/manifest/favicon-196.png"  # iPay Collect tab icon
    request_name = frappe.form_dict.get("request")

    status = None
    if request_name and frappe.db.exists("iPay Request", request_name):
        status = frappe.db.get_value("iPay Request", request_name, "status")

    context.confirmed = status == "Success"
    context.mismatch = status in ("Underpaid", "Overpaid")
    # Arrived at iPay but not yet posted. Says "received", never "confirming" — the payer
    # has paid, and telling them otherwise is what sends them round again.
    context.received = status == "Received"

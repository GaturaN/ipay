import frappe


def get_context(context):
    context.no_cache = 1
    request_name = frappe.form_dict.get("request")

    status = None
    if request_name and frappe.db.exists("iPay Request", request_name):
        status = frappe.db.get_value("iPay Request", request_name, "status")

    context.confirmed = status == "Success"
    context.mismatch = status in ("Underpaid", "Overpaid")

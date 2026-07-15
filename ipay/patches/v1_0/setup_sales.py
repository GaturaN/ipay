import frappe
from frappe.permissions import add_permission, update_permission_property


def execute():
    if not frappe.db.exists("Role", "iPay Sales"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "iPay Sales", "desk_access": 1}
        ).insert(ignore_permissions=True)

    # iPay Request's permissions are customized (Custom DocPerm), so a DocPerm row in the
    # doctype JSON is ignored. Grant read/report via the permissions API, which writes the
    # correct (Custom) DocPerm — mirroring the collector. A sales member never needs write:
    # requests are created server-side by the whitelisted collection methods.
    add_permission("iPay Request", "iPay Sales", 0)
    for ptype in ("read", "report", "print", "email", "export"):
        update_permission_property("iPay Request", "iPay Sales", 0, ptype, 1)

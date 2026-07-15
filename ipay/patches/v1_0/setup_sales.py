import frappe
from frappe.permissions import add_permission, update_permission_property


def execute():
    # "iPay Sales Manager" is an iPay-owned role rather than ERPNext's stock "Sales Manager":
    # the reps themselves hold that one, so reusing it would make every member a manager and
    # the row scoping inert.
    for role in ("iPay Sales", "iPay Sales Manager"):
        if not frappe.db.exists("Role", role):
            frappe.get_doc(
                {"doctype": "Role", "role_name": role, "desk_access": 1}
            ).insert(ignore_permissions=True)

        # iPay Request's permissions are customized (Custom DocPerm), so a DocPerm row in
        # the doctype JSON is ignored. Grant read/report via the permissions API, which
        # writes the correct (Custom) DocPerm — mirroring the collector. Neither role needs
        # write: requests are created server-side by the whitelisted collection methods.
        # Row-level narrowing for a member is layered on by the permission hooks.
        add_permission("iPay Request", role, 0)
        for ptype in ("read", "report", "print", "email", "export"):
            update_permission_property("iPay Request", role, 0, ptype, 1)

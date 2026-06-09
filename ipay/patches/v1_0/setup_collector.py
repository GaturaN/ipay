import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission, update_permission_property


def execute():
    if not frappe.db.exists("Role", "iPay Collector"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "iPay Collector", "desk_access": 1}
        ).insert(ignore_permissions=True)

    # iPay Request's permissions are customized (Custom DocPerm), so a DocPerm
    # row in the doctype JSON is ignored. Grant the collector read/report via
    # the permissions API, which writes the correct (Custom) DocPerm. Row-level
    # narrowing is layered on by the permission hooks.
    add_permission("iPay Request", "iPay Collector", 0)
    for ptype in ("read", "report", "print", "email", "export"):
        update_permission_property("iPay Request", "iPay Collector", 0, ptype, 1)

    # Map a collector's login to their Driver record, for driver-based scoping.
    create_custom_fields(
        {
            "Driver": [
                {
                    "fieldname": "user",
                    "label": "User",
                    "fieldtype": "Link",
                    "options": "User",
                    "insert_after": "employee",
                    "description": "Login mapped to this driver, for iPay Collector visibility scoping.",
                }
            ]
        },
        ignore_validate=True,
    )

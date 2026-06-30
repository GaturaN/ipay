from urllib.parse import quote

import frappe
from frappe.utils import get_system_timezone

# Entry controller for the iPay Collect SPA. The built index.html (served here as
# collect.html) is Jinja-templated by the frappeui Vite plugin and reads the
# `boot` dict below to expose window.csrf_token etc. to the Vue app. Serving the
# file as collect.html makes the app available at /collect; the website_route_rule
# in hooks.py routes /collect/<sub-path> here too so the client router owns them.
no_cache = 1


def get_context():
    # The Collect app is operator/collector-only: never serve the SPA shell to a
    # guest — send them to log in first. (Row/role scoping is still enforced in
    # every API the app calls; this just keeps the page itself behind login.)
    if frappe.session.user == "Guest":
        # Preserve the requested deep link (e.g. /collect/request/XXX) so the SPA
        # restores it after login.
        target = frappe.request.path if getattr(frappe.local, "request", None) else "/collect"
        frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target)}"
        raise frappe.Redirect

    # Operator/collector-only: a logged-in user without a collection role gets a
    # clear 403 instead of the empty SPA shell (the APIs already scope; this gates
    # the page itself, matching /collect_payments).
    from ipay.www.collect_payments import ALLOWED_ROLES

    if not set(frappe.get_roles()) & ALLOWED_ROLES:
        raise frappe.PermissionError("You do not have access to iPay Collect.")

    frappe.db.commit()
    context = frappe._dict()
    context.boot = get_boot()
    return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
    """Boot data for `yarn dev`, where Vite (not Frappe) serves the page."""
    if not frappe.conf.developer_mode:
        frappe.throw("This method is only meant for developer mode")
    return get_boot()


def get_boot():
    return frappe._dict(
        {
            "frappe_version": frappe.__version__,
            "default_route": "/collect",
            "site_name": frappe.local.site,
            "csrf_token": frappe.sessions.get_csrf_token(),
            "timezone": {
                "system": get_system_timezone(),
                "user": frappe.db.get_value("User", frappe.session.user, "time_zone")
                or get_system_timezone(),
            },
        }
    )

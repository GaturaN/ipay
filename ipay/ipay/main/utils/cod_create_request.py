import frappe
import logging

logger = logging.getLogger(__name__)

@frappe.whitelist()
def create_request(inv):
    logger.info(f"Received parameter: {inv}")

    try:
        # Fetch Sales Invoice and related Customer details
        invoice = frappe.get_doc('Sales Invoice', inv)
        customer = frappe.get_doc('Customer', invoice.customer)
        payment_terms = customer.payment_terms

        # Check if COD feature is enabled in iPay Settings
        ipay_settings = frappe.get_single('iPay Settings')
        if not ipay_settings.request_for_cod:
            return _response("error", "COD feature is disabled in iPay Settings.")

        # Proceed only if payment terms are "Cash on Delivery"
        if payment_terms != "Cash on Delivery":
            return _response("error", "Payment terms are not 'Cash on Delivery'.")

        # Create and insert iPay Request
        ipay_request = frappe.get_doc({
            'doctype': 'iPay Request',
            'customer': customer.name,
            'sales_invoice': invoice.name,
            'docstatus': 1
        })

        ipay_request.insert(ignore_permissions=True)
        logger.info(f"iPay Request created: {ipay_request.name}")

        return _response("success", ipay_request.name)

    except frappe.DoesNotExistError as e:
        logger.error(f"Document not found: {e}")
        return _response("error", f"Document not found: {e}")

    except Exception as e:
        logger.exception("An unexpected error occurred")
        return _response("error", f"Unexpected error: {e}")


def _response(status, message):
    """ Helper function to standardize responses """
    return {"status": status, "message": message}

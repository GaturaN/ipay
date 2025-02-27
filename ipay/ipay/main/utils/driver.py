import frappe
import logging

logger = logging.getLogger(__name__)

@frappe.whitelist()
def update_driver(request_name):
    """Fetch and update the driver details for an iPay Request."""
    if not request_name:
        return {"status": "error", "message": "No iPay Request provided"}

    try:
        # Step 1: Get the Sales Invoice linked to iPay Request
        sales_invoice = frappe.db.get_value("iPay Request", request_name, "sales_invoice")
        if not sales_invoice:
            return {"status": "error", "message": "No Sales Invoice linked to this iPay Request"}

        # Step 2: Get the Sales Order linked to the Sales Invoice
        sales_order_list = frappe.db.get_list(
            "Sales Invoice Item",
            filters={"parent": sales_invoice},
            fields=["sales_order"],
            limit=1
        )
        if not sales_order_list:
            return {"status": "error", "message": "No Sales Order linked to this Sales Invoice"}

        sales_order = sales_order_list[0]["sales_order"]

        # Step 3: Get the Delivery Note linked to the Sales Order
        delivery_note_list = frappe.db.get_list(
            "Delivery Note",
            filters={"against_sales_order": sales_order},
            fields=["name", "driver", "driver_name"],
            limit=1
        )
        if not delivery_note_list:
            return {"status": "error", "message": "No Delivery Note linked to this Sales Order"}

        dn_driver = delivery_note_list[0]["driver"]
        dn_driver_name = delivery_note_list[0]["driver_name"]

        # Step 4: Update the iPay Request with the driver details
        frappe.db.set_value("iPay Request", request_name, {"driver": dn_driver, "driver_name": dn_driver_name})
        frappe.db.commit()

        return {
            "status": "success",
            "message": "Driver details updated successfully",
            "driver": dn_driver,
            "driver_name": dn_driver_name
        }

    except Exception as error:
        logger.error(f"Error updating driver for iPay Request {request_name}: {error}")
        return {"status": "error", "message": str(error)}

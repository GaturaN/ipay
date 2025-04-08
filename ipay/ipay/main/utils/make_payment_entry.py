import frappe
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@frappe.whitelist()
def make_payment_entry(user_id, customer_email, inv, response_data):
    try:
        # Log the received parameters
        logger.info(f"Received doc name: {inv}")
        logger.info(f"Customer Email: {customer_email}")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Response Data: {response_data}")

        # Ensure response_data is a dictionary
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except json.JSONDecodeError:
                logger.error("Invalid JSON in response_data")
                return {"status": "error", "message": "Invalid JSON in response_data"}

        # Extract transaction code
        transaction_code = response_data.get("transaction_code")
        if transaction_code:
            existing_payment = frappe.db.exists(
                "Payment Entry", {"reference_no": transaction_code}
            )
            if existing_payment:
                logger.warning(f"Duplicate Payment Entry found: {existing_payment}")
                return {
                    "status": "duplicate",
                    "message": f"Payment Entry already exists with transaction code {transaction_code}",
                    "payment_entry": existing_payment,
                }

        # Fetch the Sales Invoice
        sales_invoice = frappe.get_doc("Sales Invoice", inv)
        payment_terms = (
            getattr(sales_invoice, "payment_terms_template", None) or "Cash on Delivery"
        )
        logger.info(f"Sales Invoice {inv} - Payment Terms: {payment_terms}")

        # Fetch the cash account
        cash_account = frappe.get_value(
            "Account",
            {"account_type": "Cash", "company": sales_invoice.company, "is_group": 0},
            "name",
        )

        if not cash_account:
            logger.error("Cash Account not found")
            frappe.log_error("Cash Account not found", "Payment Entry Creation Error")
            return {"status": "error", "message": "Cash Account not found"}

        # Create Payment Entry
        transaction_amount = float(response_data.get("transaction_amount", 0))
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.update(
            {
                "payment_type": "Receive",
                "payment_order_status": "Initiated",
                "posting_date": frappe.utils.today(),
                "mode_of_payment": "Ipay Mpesa",
                "party_type": "Customer",
                "party": sales_invoice.customer,
                "party_name": sales_invoice.customer_name,
                "paid_to": cash_account,
                "paid_amount": transaction_amount,
                "base_paid_amount": transaction_amount,
                "received_amount": transaction_amount,
                "base_received_amount": transaction_amount,
                "source_exchange_rate": 1.0,
                "target_exchange_rate": 1.0,
                "unallocated_amount": transaction_amount,
                "reference_no": transaction_code,
                "reference_date": response_data.get("paid_at", frappe.utils.today()),
                "custom_remarks": 1,
                "remarks": (
                    f"Amount KES {transaction_amount} received from {sales_invoice.customer} - {response_data.get('payee')} "
                    f"against Sales Invoice {sales_invoice.name}\n"
                    f"Transaction reference no {transaction_code} dated {response_data.get('paid_at', frappe.utils.today())}"
                ),
            }
        )

        payment_entry.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice.name,
                "allocated_amount": transaction_amount,
                "payment_term": payment_terms,
            },
        )

        # Save and Submit
        payment_entry.insert()
        payment_entry.submit()

        logger.info(f"Payment Entry {payment_entry.name} created successfully.")
        return {"status": "success", "payment_entry": payment_entry.name}

    except Exception as e:
        logger.error(f"Error creating Payment Entry: {str(e)}", exc_info=True)
        frappe.log_error(frappe.get_traceback(), "Payment Entry Creation Error")
        return {"status": "error", "message": str(e)}

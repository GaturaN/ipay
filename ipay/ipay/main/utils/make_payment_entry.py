import frappe
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def make_payment_entry(user_id, customer_email, inv, response_data):
    try:
        # Log the received parameters
        logger.info(f"Received doc name: {inv}")
        logger.info(f"Customer Email: {customer_email}")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Response Data: {response_data}")
        
        # Fetch the Sales Invoice
        sales_invoice = frappe.get_doc("Sales Invoice", inv)
        if not sales_invoice:
            logger.error(f"Sales Invoice {inv} not found")
            return

        # Fetch the cash account
        cash_account = frappe.get_value("Account", {"account_type": "Cash","company": sales_invoice.company, "is_group": 0}, "name")
        logger.info(f"Cash Account: {cash_account}")
        if not cash_account:
          logger.error(f"Cash Account not found")
          frappe.log_error(f"Cash Account not found", "Payment Entry Creation Error")
        
        # Create a new Payment Entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.payment_order_status = "Initiated"
        payment_entry.posting_date = frappe.utils.today()
        payment_entry.mode_of_payment = "MPESA"
        payment_entry.party_type = "Customer"
        payment_entry.party = sales_invoice.customer
        payment_entry.party_name = sales_invoice.customer_name
        payment_entry.paid_to = cash_account  #dynamically get the name of the cash account

        # Transaction amount
        transaction_amount = float(response_data.get("transaction_amount", 0))
        payment_entry.paid_amount = transaction_amount
        payment_entry.source_exchange_rate = 1.0
        payment_entry.base_paid_amount = transaction_amount
        payment_entry.received_amount = transaction_amount
        payment_entry.target_exchange_rate = 1.0
        payment_entry.base_received_amount = transaction_amount
        payment_entry.unallocated_amount = transaction_amount
        payment_entry.reference_no = response_data.get("transaction_code", "")
        payment_entry.reference_date = response_data.get("paid_at", frappe.utils.today())
        payment_entry.remarks = (
            f"Amount KES {transaction_amount} received from {response_data.get('names', '')}\n"
            f"Transaction reference no {response_data.get('transaction_code', '')} dated {response_data.get('paid_at', frappe.utils.today())}"
        )

        # Add references (linked Sales Invoice)
        payment_entry.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": sales_invoice.name,
            "allocated_amount": transaction_amount
        })

        # Add deductions (if any)
        payment_entry.deductions = []

        # Save and Submit the Payment Entry
        payment_entry.insert()
        payment_entry.submit()

        # Log success
        logger.info(f"Payment Entry {payment_entry.name} created successfully for Sales Invoice {inv}.")
        return payment_entry.name

    except Exception as e:
        # Log the exception
        logger.error(f"Error creating Payment Entry: {str(e)}", exc_info=True)
        frappe.log_error(frappe.get_traceback(), "Payment Entry Creation Error")
        return None

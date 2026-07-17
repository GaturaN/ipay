import frappe
import logging
import json

logger = logging.getLogger(__name__)


def allocate_references(invoice_names, amount):
    """Split `amount` across invoices oldest-first, per payment term where the invoice has them.

    Returns (invoices, references, remaining) — `remaining` is unallocated customer credit. Shared
    by every rail: allocation belongs to the invoices, not to how the money arrived."""
    flt = frappe.utils.flt

    # Read outstanding live, so an invoice settled elsewhere meanwhile is skipped.
    invoices = sorted(
        (
            frappe.db.get_value(
                "Sales Invoice",
                name,
                ["name", "outstanding_amount", "posting_date", "customer", "customer_name", "company"],
                as_dict=True,
            )
            for name in invoice_names
        ),
        key=lambda si: (si.posting_date, si.name),
    )

    remaining = flt(amount)
    references = []
    for si in invoices:
        if remaining <= 0:
            break
        if flt(si.outstanding_amount) <= 0:
            continue

        # Invoices with payment terms must allocate per term (oldest due first) and carry the
        # payment_term on the reference; others take a single reference.
        terms = [
            t
            for t in frappe.get_all(
                "Payment Schedule",
                filters={"parent": si.name, "parenttype": "Sales Invoice"},
                fields=["payment_term", "outstanding"],
                order_by="due_date asc",
            )
            if flt(t.outstanding) > 0
        ]
        if terms:
            for term in terms:
                if remaining <= 0:
                    break
                allocated = min(remaining, flt(term.outstanding))
                references.append(
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": si.name,
                        "payment_term": term.payment_term,
                        "allocated_amount": allocated,
                    }
                )
                remaining = flt(remaining - allocated)
        else:
            allocated = min(remaining, flt(si.outstanding_amount))
            references.append(
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": si.name,
                    "allocated_amount": allocated,
                }
            )
            remaining = flt(remaining - allocated)

    return invoices, references, remaining


# NOT @frappe.whitelist: this is an internal helper called only by
# finalize_payment (server-side). Exposing it let any authenticated user POST a
# forged response_data (fake transaction_code + amount) and submit a Payment
# Entry marking an invoice paid with no real money — so it must not be callable
# over HTTP.
def make_payment_entry(user_id, customer_email, inv, response_data, ipay_request=None):
    try:
        # Log the received parameters
        logger.info(f"Received doc name: {inv}")
        logger.info(f"Customer Email: {customer_email}")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Response Data: {response_data}")

        # Ensure response_data is a dictionary
        if isinstance(response_data, str):
            response_data = json.loads(response_data)

        # Idempotency: never create a second Payment Entry for the same M-Pesa
        # transaction. Multiple paths (STK, manual confirm, callback) can finalise
        # the same payment, so guard on the transaction code.
        transaction_code = response_data.get("transaction_code")
        if transaction_code:
            existing = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": transaction_code, "docstatus": ["<", 2]},
                "name",
            )
            if existing:
                logger.info(
                    f"Payment Entry {existing} already exists for transaction {transaction_code}"
                )
                if ipay_request:
                    frappe.db.set_value("iPay Request", ipay_request, "payment_entry", existing)
                # Report how much the existing entry allocated to invoices, so the
                # caller resolves the same status on a re-run instead of assuming a
                # duplicate was fully allocated.
                return {
                    "status": "duplicate",
                    "payment_entry": existing,
                    "allocated": frappe.utils.flt(
                        frappe.db.get_value("Payment Entry", existing, "total_allocated_amount")
                    ),
                    "message": "Payment Entry already exists",
                }

        flt = frappe.utils.flt

        # Resolve the invoices this payment covers: a bundle uses the iPay
        # Request's child table; a single request uses the one Sales Invoice.
        invoice_names = []
        if ipay_request:
            invoice_names = [
                name
                for name in frappe.get_all(
                    "iPay Request Invoice",
                    filters={"parent": ipay_request, "parenttype": "iPay Request"},
                    pluck="sales_invoice",
                )
                if name
            ]
        if not invoice_names:
            invoice_names = [inv]

        transaction_amount = flt(response_data.get("transaction_amount", 0))
        invoices, references, remaining = allocate_references(invoice_names, transaction_amount)
        primary = invoices[0]

        # If nothing could be allocated (every invoice was already settled
        # elsewhere), the money is still real — record it as unallocated credit,
        # but make it auditable instead of a silent full-credit Payment Entry.
        if not references:
            logger.warning(
                f"No outstanding to allocate for {ipay_request or inv}; "
                f"recording {transaction_amount} as unallocated customer credit"
            )
            frappe.log_error(
                f"iPay payment {response_data.get('transaction_code')} recorded as unallocated "
                f"credit — invoices already settled ({ipay_request or inv})",
                "iPay unallocated payment",
            )

        # Resolve the receiving account per the invoice's company: prefer the
        # company's default cash account, then an iPay Settings override, then the
        # MPESA mode-of-payment account mapped to this company. Setting company
        # explicitly keeps multi-company correct. Fail loudly if none is
        # configured rather than booking to a hardcoded, company-specific account
        # (which silently loses the payment on any other site/company).
        company = primary.company
        cash_account = (
            frappe.get_cached_value("Company", company, "default_cash_account")
            or frappe.db.get_single_value("iPay Settings", "cash_account")
            or frappe.db.get_value(
                "Mode of Payment Account",
                {"parent": "MPESA", "company": company},
                "default_account",
            )
        )
        if not cash_account:
            frappe.throw(
                f"No receiving account is configured for {company}. Set a Default "
                f"Cash Account on the Company, or set iPay Settings → Cash Account "
                f"(fallback)."
            )

        # Create a new Payment Entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.company = company
        payment_entry.payment_order_status = "Initiated"
        payment_entry.posting_date = frappe.utils.today()
        payment_entry.mode_of_payment = "MPESA"
        payment_entry.party_type = "Customer"
        payment_entry.party = primary.customer
        payment_entry.party_name = primary.customer_name
        payment_entry.paid_to = cash_account

        payment_entry.paid_amount = transaction_amount
        payment_entry.source_exchange_rate = 1.0
        payment_entry.base_paid_amount = transaction_amount
        payment_entry.received_amount = transaction_amount
        payment_entry.target_exchange_rate = 1.0
        payment_entry.base_received_amount = transaction_amount
        # Whatever could not be allocated to an invoice (overpayment) stays as
        # unallocated customer credit. ERPNext recomputes this on validate.
        payment_entry.unallocated_amount = remaining
        payment_entry.reference_no = response_data.get("transaction_code", "")
        payment_entry.reference_date = response_data.get(
            "paid_at", frappe.utils.today()
        )
        payment_entry.custom_remarks = 1
        allocated_to = ", ".join(r["reference_name"] for r in references) or primary.name
        payment_entry.remarks = (
            f"Amount KES {transaction_amount} received from {primary.customer} - {response_data.get('payee')} against {allocated_to}\n"
            f"Transaction reference no {response_data.get('transaction_code', '')} dated {response_data.get('paid_at', frappe.utils.today())}"
        )

        for ref in references:
            payment_entry.append("references", ref)

        # Add deductions (if any)
        payment_entry.deductions = []

        # Save and Submit the Payment Entry. If a concurrent finaliser inserted
        # the same M-Pesa transaction first, the DB unique index on reference_no
        # rejects ours — treat that as a duplicate (use the winner's entry) rather
        # than a hard error, so this caller still resolves the status and delivers
        # the callback. (finalize_payment also row-locks the request to serialise
        # these, so this is the belt-and-braces path / portability for sites
        # without the unique index.)
        try:
            payment_entry.insert()
            payment_entry.submit()
        except Exception as insert_error:
            # Roll back FIRST, then re-read: under REPEATABLE READ a read earlier
            # in this transaction pins a snapshot that would hide the winner's
            # concurrently-committed entry, so we must reset the snapshot before
            # checking (and the failed insert pinned nothing worth keeping).
            # NB: this is a FULL rollback (a savepoint would not reset the
            # snapshot). It is safe because the only caller, finalize_payment,
            # holds no other uncommitted writes when it reaches here.
            frappe.db.rollback()
            existing = transaction_code and frappe.db.get_value(
                "Payment Entry",
                {"reference_no": transaction_code, "docstatus": ["<", 2]},
                "name",
            )
            if not existing:
                raise
            logger.warning(
                f"Concurrent Payment Entry for transaction {transaction_code}; "
                f"using existing {existing} ({insert_error})"
            )
            if ipay_request:
                frappe.db.set_value("iPay Request", ipay_request, "payment_entry", existing)
            return {
                "status": "duplicate",
                "payment_entry": existing,
                "allocated": frappe.utils.flt(
                    frappe.db.get_value("Payment Entry", existing, "total_allocated_amount")
                ),
                "message": "Payment Entry already exists (concurrent)",
            }

        # Log success
        logger.info(
            f"Payment Entry {payment_entry.name} created successfully for Sales Invoice {inv}."
        )
        if ipay_request:
            frappe.db.set_value("iPay Request", ipay_request, "payment_entry", payment_entry.name)
        return {
            "status": "success",
            "payment_entry": payment_entry.name,
            "allocated": float(transaction_amount - remaining),
            "message": "Payment Entry created",
        }

    except Exception as e:
        # Log the exception
        logger.error(f"Error creating Payment Entry: {str(e)}", exc_info=True)
        frappe.log_error(frappe.get_traceback(), "Payment Entry Creation Error")
        return {"status": "error", "payment_entry": None, "message": str(e)}

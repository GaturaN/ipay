import frappe

INVOICE = "iPay: Invoice Issued"
REMINDER = "iPay: Payment Reminder"

_BUTTON = (
	"{% set link = ipay_payment_link(doc.name) %}\n"
	'{% if link %}<p><a href="{{ link }}" '
	'style="background:#007a36;color:#ffffff;padding:10px 18px;'
	'border-radius:6px;text-decoration:none;">Pay now</a></p>{% endif %}'
)

INVOICE_MESSAGE = (
	"<p>Dear {{ doc.customer_name }},</p>\n"
	"<p>Invoice <strong>{{ doc.name }}</strong> for "
	"<strong>{{ frappe.utils.fmt_money(doc.outstanding_amount, currency=doc.currency) }}</strong> "
	"has been issued{% if doc.due_date %}, due {{ frappe.utils.formatdate(doc.due_date) }}{% endif %}.</p>\n"
	f"{_BUTTON}\n<p>Thank you.</p>"
)

REMINDER_MESSAGE = (
	"<p>Dear {{ doc.customer_name }},</p>\n"
	"<p>This is a reminder that invoice <strong>{{ doc.name }}</strong> for "
	"<strong>{{ frappe.utils.fmt_money(doc.outstanding_amount, currency=doc.currency) }}</strong> "
	"remains unpaid{% if doc.due_date %} (due {{ frappe.utils.formatdate(doc.due_date) }}){% endif %}.</p>\n"
	f"{_BUTTON}\n<p>Thank you.</p>"
)


def _create(name, subject, message, event, extra):
	if frappe.db.exists("Notification", name):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Notification",
			"name": name,
			"subject": subject,
			"document_type": "Sales Invoice",
			"channel": "Email",
			"event": event,
			"enabled": 0,
			"is_standard": 0,
			"condition": "doc.outstanding_amount > 0",
			"message": message,
			"recipients": [{"receiver_by_document_field": "contact_email"}],
			**extra,
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert()


def execute():
	"""Ship two disabled, editable email notifications that carry the iPay payment link — an
	'invoice issued' email on submit, and a 'payment reminder' a few days after the due date.
	Created once and never re-synced, so a site can enable, edit or delete them freely."""
	_create(INVOICE, "Invoice {{ doc.name }} — payment options", INVOICE_MESSAGE, "Submit", {})
	_create(
		REMINDER,
		"Reminder: invoice {{ doc.name }} is due",
		REMINDER_MESSAGE,
		"Days After",
		{"date_changed": "due_date", "days_in_advance": 3},
	)

"""Jinja helpers exposed to email templates, notifications and print formats (see hooks.jinja)."""

from ipay.ipay.main.utils.ipay_redirect import payment_link_for_invoice


def ipay_payment_link(invoice):
	"""A customer-facing pay link for a Sales Invoice, or None. Drop into any template:
	{% set link = ipay_payment_link(doc.name) %}{% if link %}<a href="{{ link }}">Pay now</a>{% endif %}
	"""
	return payment_link_for_invoice(invoice)

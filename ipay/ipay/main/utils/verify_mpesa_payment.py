import time
import logging
import requests
import frappe
from requests.exceptions import RequestException

from ipay.ipay.main.utils.constants import search_hash

logger = logging.getLogger(__name__)

# iPay returns these in the transaction/search response when an STK finished but
# did not succeed. Map the known terminal messages to a friendly one; anything
# else ("no payment record found", "transaction was timed out", ...) is transient
# and the caller keeps polling. NB: this classifies iPay's free-text `message`;
# the raw response is logged on every attempt so a wrong classification (e.g. a
# cancel reported as insufficient) can be traced to exactly what iPay returned.
TERMINAL_ERRORS = {
    "The request was canceled by the user": "The request was canceled by the user",
    "Incorrect pin has been entered": "Incorrect PIN entered",
    "The User Wallet balance is insufficient for the transaction": "Insufficient M-Pesa balance",
}


def _terminal_error_message(response):
    """Friendly message if iPay reported a terminal STK failure, else None."""
    if response is None:
        return None
    try:
        message = (response.json() or {}).get("message") or ""
    except ValueError:
        return None
    for needle, friendly in TERMINAL_ERRORS.items():
        if needle in message:
            return friendly
    return None


# Helper function to delay execution
def delay(ms):
    time.sleep(ms / 1000.0)

# Isolate the API call to a separate function
def make_verification_call(verification_payload):
    response = requests.post(
        'https://apis.ipayafrica.com/payments/v2/transaction/search',
        data=verification_payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    # Raise errors for bad status codes
    response.raise_for_status()
    return response

# Handle payment verification
def verify_mpesa_payment(oid, phone, vid, secret_key):
    max_retries = 20
    initial_delay = 4000
    retry_delay = 2000
    
    # Initial delay before verification
    delay(initial_delay)
    
    hash_value = search_hash(oid, vid, secret_key)
    verification_payload = {
        'vid': vid,
        'hash': hash_value,
        'oid': oid
    }
    
    attempt = 0
    success = False
    
    while attempt < max_retries and not success:
        try:
            attempt += 1
            logger.info(f'Attempt {attempt}: Verifying Payment...')
            
            # Make the verification call
            verification_response = make_verification_call(verification_payload)
            
            if verification_response.status_code == 200:
                logger.info('Payment verification successful')
                success = True
                
                # data = verification_response.json().get('data', {})
                # transaction_code = data.get('transaction_code')
                # transaction_amount = data.get('transaction_amount')
                
                return verification_response.json()                
                
            else:
                logger.warning(
                    f"Attempt {attempt}: Payment not found with status code {verification_response.status_code}. Retrying..."
                )
                
                delay(retry_delay)
        
        except requests.RequestException as error:
            # Log the FULL raw iPay response on every failed attempt, BEFORE any
            # throw — previously the decisive response was never logged (the
            # throw happened first), which is why a cancel showing as
            # "insufficient" could not be diagnosed.
            raw = error.response.text if error.response is not None else str(error)
            logger.error(f"Attempt {attempt}: iPay verification error — {raw}")

            terminal = _terminal_error_message(error.response)
            if terminal:
                frappe.throw(terminal)
            # Otherwise transient (e.g. "no payment record found", timeout) — keep polling.
            delay(retry_delay)
    
    if not success:
        logger.error("Max retries reached. Payment verification failed.")
        frappe.msgprint("Max retries reached. Payment verification failed.")
        return None
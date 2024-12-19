import requests
import hmac
import hashlib
import time
import logging
import frappe  

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper function to delay execution
def delay(ms):
    time.sleep(ms / 1000)
    
# Helper function to create HMAC hash
def create_hash(oid, vid, secret_key):
    data_string = f'{oid}{vid}'
    return hmac.new(secret_key.encode(), data_string.encode(), hashlib.sha256).hexdigest()

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
def verify_mpesa_payment(oid, type, phone, vid, secret_key):
    max_retries = 30
    initial_delay = 4000
    retry_delay = 2000
    
    # Initial delay before verification
    delay(initial_delay)
    
    hash_value = create_hash(oid, vid, secret_key)
    verification_payload = {
        'vid': vid,
        'oid': oid,
        'hash': hash_value
    }
    
    attempt = 0
    success = False
    
    while attempt < max_retries and not success:
        try:
            attempt += 1
            logger.info(f'Attempt {attempt}: Verifying Payment...')
            frappe.msgprint(f'Attempt {attempt}: Verifying Payment...')
            
            # Make the verification call
            verification_response = make_verification_call(verification_payload)
            
            if verification_response.status_code == 200:
                logger.info('Payment verification successful')
                frappe.msgprint('Payment verification successful')
                success = True
                
                response_json = verification_response.json() or {}
                data = response_json.get('data', {})
                
                transaction_code = data.get('transaction_code')
                transaction_amount = data.get('transaction_amount')
                
                return response_json
            
            else:
                logger.warning(
                    f"Attempt {attempt}: Payment not found with status code {verification_response.status_code}. Retrying..."
                )
                frappe.msgprint(
                    f"Attempt {attempt}: Payment not found. Retrying..."
                )
                delay(retry_delay)
        
        except requests.RequestException as error:
            error_message = (
                error.response.json().get('message')
                if error.response and error.response.content
                else str(error)
            )
            logger.error(
                f"Attempt {attempt}: Error verifying payment: {error_message}. Retrying..."
            )
            frappe.msgprint(
                f"Attempt {attempt}: Error verifying payment: {error_message}. Retrying..."
            )
            delay(retry_delay)
    
    if not success:
        logger.error("Max retries reached. Payment verification failed.")
        frappe.msgprint("Max retries reached. Payment verification failed.")
        return None

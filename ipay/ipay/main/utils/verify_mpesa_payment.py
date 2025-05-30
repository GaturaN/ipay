import requests
import hmac
import hashlib
import time
import logging
import frappe 
from requests.exceptions import RequestException 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper function to delay execution
def delay(ms):
    time.sleep(ms / 1000.0)
    
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
def verify_mpesa_payment(oid, phone, vid, secret_key):
    max_retries = 20
    initial_delay = 4000
    retry_delay = 2000
    
    # Initial delay before verification
    delay(initial_delay)
    
    hash_value = create_hash(oid, vid, secret_key)
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
            error_message = (
                error.response.json().get('message')
                if error.response is not None else str(error)
            )
            
            # check if the request was canceled by the user
            if "The request was canceled by the user" in error_message:
              message = "The request was canceled by the user"
              frappe.throw(message)
              # return message 
            
            elif "Incorrect pin has been entered" in error_message:
              message = "Incorrect pin has been entered"
              frappe.throw(message)
              
            elif "The User Wallet balance is insufficient for the transaction" in error_message:
              message = "The User has insufficient funds"
              frappe.throw(message)
              
            elif "The transaction was timed out" in error_message:
              message = "The transaction was timed out"
              frappe.throw(message)
            
            logger.error(
                f"Attempt {attempt}: Failed due to an error: {error_message}\nRetrying..."
            )
            
            
            delay(retry_delay)
    
    if not success:
        logger.error("Max retries reached. Payment verification failed.")
        frappe.msgprint("Max retries reached. Payment verification failed.")
        return None
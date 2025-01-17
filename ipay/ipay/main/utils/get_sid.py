import requests
import hmac
import hashlib
import logging
import frappe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_sid(vid: str, secret_key: str, amount: str, oid: str, phone: str) -> dict:

    try:
        inv = oid
        
        # customer's email address => value from api.py
        eml = frappe.db.get_value("Sales Invoice", inv, "contact_email")
        # if email is None, set a default
        if not eml:
            eml = 'gaturanjenga@gmail.com'
        
        # callback url for payment status
        cbk = frappe.get_doc("iPay Settings").callback_url
        
        # set to 1 for live, make sure it is string
        isLive = frappe.get_doc("iPay Settings").is_live
        live = str(isLive)
        
        # default currency
        curr = 'KES'
        
        # Allow customer to receive transaction notifications
        cst = '0'
        
        # Default to 0 for HTTP/HTTPS callback
        crl = '0'
        
        # Generate the data string for hashing
        data_string = f'{live}{oid}{inv}{amount}{phone}{eml}{vid}{curr}{cst}{cbk}'
        
        # Generate the hash using HMAC SHA256
        hash_value = hmac.new(secret_key.encode(),data_string.encode(),hashlib.sha256).hexdigest()
        
        # Prepare the transaction payload
        transaction_payload = {
            'live': live,
            'oid': oid,
            'inv': inv,
            'amount': amount,
            'tel': phone,
            'eml': eml,
            'vid': vid,
            'curr': curr,
            'cbk': cbk,
            'cst': cst,
            'crl': crl,
            'hash': hash_value
        }
        
        # Send a POST request
        response = requests.post(
            'https://apis.ipayafrica.com/payments/v2/transact',
            data=transaction_payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        # raise HTTP error for bad responses
        response.raise_for_status()
        logger.info('SID served successfully')
        logger.info(response.json())
        return response.json()
        
    except requests.RequestException as error:
        logger.error("Error getting SID: %s", error)
        raise RuntimeError("Error getting SID") from error
      
      
      

# 16:23:58 web.1         | INFO:ipay.ipay.main.utils.get_sid:{'header_status': 200, 'status': 1, 'data': {'sid': 'ACCBUL317051737028143174051052BULKBOX', 'oid': 'ACCSINV202500026', 'amount': '1', 'account': 'JT515144903L07', 'payment_channels': [{'name': 'MPESA', 'paybill': '510800'}, {'name': 'AIRTEL', 'paybill': '510800'}, {'name': 'EQUITEL', 'paybill': '510800'}], 'hash': '465ec2ddae64df78bd10d339e404d111bd3d6d840312b276ae712b1334e373a0'}}
# 
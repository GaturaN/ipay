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
        
        # Fetch Sales Invoice email
        eml = frappe.db.get_value("Sales Invoice", inv, "contact_email") or ""
        
        # Fetch iPay Settings once
        ipay_settings = frappe.get_single("iPay Settings")
        
        # Get callback URL safely
        cbk = getattr(ipay_settings, "callback_url", "") or ""
        logger.info(f"Callback URL: {cbk if cbk else 'Empty string'}")
        
        # Get 'is_live' safely (default to 0 if missing)
        is_live = getattr(ipay_settings, "is_live", 0)
        live = str(int(is_live))  # Convert boolean to "1" or "0"
        
        # Default currency
        curr = 'KES'
        
        # Allow customer to receive transaction notifications
        cst = '0'
        
        # Default to 0 for HTTP/HTTPS callback
        crl = '0'
        
        # Generate the data string for hashing
        data_string = f"{live}{oid}{inv}{amount}{phone}{eml}{vid}{curr}{cst}{cbk}"
        
        # Generate the hash using HMAC SHA256
        hash_value = hmac.new(secret_key.encode(), data_string.encode(), hashlib.sha256).hexdigest()
        
        # Prepare the transaction payload
        transaction_payload = {
            "live": live,
            "oid": oid,
            "inv": inv,
            "amount": amount,
            "tel": phone,
            "eml": eml,
            "vid": vid,
            "curr": curr,
            "cbk": cbk,
            "cst": cst,
            "crl": crl,
            "hash": hash_value
        }
        
        logger.info("Sending iPay transaction request: %s", transaction_payload)
        
        # Send a POST request
        response = requests.post(
            "https://apis.ipayafrica.com/payments/v2/transact",
            data=transaction_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15  
        )
        
        # Raise HTTP error for bad responses
        response.raise_for_status()
        
        logger.info("SID served successfully")
        response_json = response.json()
        logger.info("Response: %s", response_json)
        
        return response_json

    except requests.Timeout:
        logger.error("Request to iPay timed out")
        return {"error": "Request timed out"}
    
    except requests.RequestException as error:
        logger.error("Error getting SID: %s", error)
        return {"error": str(error)}

    except frappe.DoesNotExistError:
        logger.error("iPay Settings doctype not found")
        return {"error": "iPay settings not found"}
    
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        return {"error": str(e)}

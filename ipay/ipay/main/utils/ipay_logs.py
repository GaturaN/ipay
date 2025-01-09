import frappe
from datetime import datetime

def create_log_entry(log_type, description):
  """
  Create a log entry in the iPay Logs Doctype.
  
  Args:
      log_type (str): The type of the log (INF, ERR)
      description (str): The description of the log 
  """
  
  try:
    log_entry = frappe.get_doc({
      "doctype": "iPay Logs",
      "type": log_type,
      "description": description,
      "time": datetime.now()
    })
    log_entry.insert(ignore_permissions=True)
    frappe.db.commit()
  
  except Exception as e:
    frappe.log_error(f"Failed to create log entry: {str(e)}", "iPay Logs Error")
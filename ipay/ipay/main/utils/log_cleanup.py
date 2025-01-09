import frappe
from datetime import datetime, timedelta

def del_old_logs():
    try:
        # Calculate thresholds
        inf_threshold = datetime.now() - timedelta(days=5)
        err_threshold = datetime.now() - timedelta(days=10)
        
        # Get logs to delete
        inf_logs = frappe.get_all("iPay Logs", 
            filters={"log_type": "INF", "time": ["<", inf_threshold]},
            pluck="name")
            
        err_logs = frappe.get_all("iPay Logs",
            filters={"log_type": "ERR", "time": ["<", err_threshold]},
            pluck="name")

        # Batch delete in chunks of 1000
        batch_size = 1000
        
        for i in range(0, len(inf_logs), batch_size):
            batch = inf_logs[i:i + batch_size]
            frappe.db.sql("""DELETE FROM `tabIPay Logs` WHERE name IN %s""", [batch])
            frappe.db.commit()
        
        for i in range(0, len(err_logs), batch_size):
            batch = err_logs[i:i + batch_size]
            frappe.db.sql("""DELETE FROM `tabIPay Logs` WHERE name IN %s""", [batch])
            frappe.db.commit()

        # Log results
        frappe.logger().info(f"Deleted {len(inf_logs)} INF logs and {len(err_logs)} ERR logs")

    except Exception as e:
        frappe.log_error(f"Error deleting old logs: {str(e)}", "Log Cleanup Error")
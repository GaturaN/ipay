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

        # Delete INF logs
        if inf_logs_to_delete:
            for log_name in inf_logs_to_delete:
                frappe.delete_doc("iPay Logs", log_name, ignore_permissions=True)
            frappe.db.commit()  # Commit changes after deletion
        else:
            frappe.logger().info("No old 'INF' logs to delete.")
    
        # Delete ERR logs
        if err_logs_to_delete:
            for log_name in err_logs_to_delete:
                frappe.delete_doc("iPay Logs", log_name, ignore_permissions=True)
            frappe.db.commit()  # Commit changes after deletion
        else:
            frappe.logger().info("No old 'ERR' logs to delete.")          
            
        # Log results
        frappe.logger().info(f"Deleted {len(inf_logs)} INF logs and {len(err_logs)} ERR logs")

    except Exception as e:
        frappe.log_error(f"Error deleting old logs: {str(e)}", "Log Cleanup Error")
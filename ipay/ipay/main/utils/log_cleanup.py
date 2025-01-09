import frappe
from datetime import datetime, timedelta

def del_old_logs():
    """
    Deletes iPay logs of type 'INF' that are older than 5 days 
    and of type 'ERR' that are older than 10 days
    """ 
    try:
        # Calculate the threshold days
        inf_threshold = datetime.now() - timedelta(days=5)
        err_threshold = datetime.now() - timedelta(days=10)
        
        # Find logs of type 'INF' older than 5 days
        inf_logs_to_delete = frappe.get_all(
            "iPay Logs",
            filters={"type": "INF", "time": ["<", inf_threshold]},
            pluck="name"
        )
        
        # Find logs of type 'ERR' older than 10 days
        err_logs_to_delete = frappe.get_all(
            "iPay Logs",
            filters={"type": "ERR", "time": ["<", err_threshold]},
            pluck="name"
        )
        
        # Delete INF logs
        if inf_logs_to_delete:
            for log_name in inf_logs_to_delete:
                frappe.delete_doc("iPay Logs", log_name, ignore_permissions=True)
            frappe.db.commit()  # Commit changes after deletion
            frappe.logger().info(f"Deleted {len(inf_logs_to_delete)} old 'INF' logs.")
        else:
            frappe.logger().info("No old 'INF' logs to delete.")
        
        # Delete ERR logs
        if err_logs_to_delete:
            for log_name in err_logs_to_delete:
                frappe.delete_doc("iPay Logs", log_name, ignore_permissions=True)
            frappe.db.commit()  # Commit changes after deletion
            frappe.logger().info(f"Deleted {len(err_logs_to_delete)} old 'ERR' logs.")
        else:
            frappe.logger().info("No old 'ERR' logs to delete.")
    
    except Exception as e:
        frappe.log_error(f"Error deleting old logs: {str(e)}", "Log Cleanup Error")

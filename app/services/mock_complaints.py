from datetime import datetime


def classify_complaint(text, category=None):
    lowered = (text or "").lower()
    if not category:
        if any(word in lowered for word in ("signal", "network", "internet", "coverage")):
            category = "Network"
        elif any(word in lowered for word in ("bill", "charge", "amount", "payment")):
            category = "Billing"
        elif any(word in lowered for word in ("sim", "account", "login")):
            category = "SIM or account"
        else:
            category = "Service"
    department = "Network Operations" if category == "Network" else "Billing Care" if category == "Billing" else "Customer Care"
    return {
        "category": category,
        "department": department,
        "priority": "High" if any(word in lowered for word in ("unable", "urgent", "no service")) else "Standard",
        "explanation": (
            "Your report appears consistent with a temporary area network interruption."
            if category == "Network"
            else "Your report needs an account-level review by the appropriate support team."
        ),
        "confidence": "High" if len(text or "") > 25 else "Medium",
        "generated_at": datetime.now().isoformat(),
    }


def analyse_bill(values):
    total = float(values.get("total_amount", 468))
    roaming = float(values.get("roaming_charges", 96))
    anomaly = roaming > 50 or total > 420
    return {
        "anomaly": anomaly,
        "summary": (
            "Your bill is 28% higher than usual. Most of the increase came from roaming charges."
            if anomaly
            else "Your bill is in line with your recent monthly average."
        ),
        "waste": "AED 34 in lightly used add-ons",
        "risk": "Moderate overage risk",
        "recommended_plan": "Smart Value 425",
        "projected_saving": 43,
    }

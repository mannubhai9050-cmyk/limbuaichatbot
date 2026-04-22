import httpx
from app.core.config import PLANS_API_URL

# Cache plans in memory
_plans_cache = None


def get_plans() -> dict:
    """Fetch plans from Limbu.ai API with caching"""
    global _plans_cache
    if _plans_cache:
        return _plans_cache
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(PLANS_API_URL)
            data = res.json()
            billing = data.get("data", {}).get("billingCycles") or data.get("billingCycles", [])
            _plans_cache = _build_plans_map(billing)
            return _plans_cache
    except Exception as e:
        print(f"[Plans] Error: {e}")
        return _get_default_plans()


def _build_plans_map(billing_cycles: list) -> dict:
    """Build easy lookup map: {cycle: {plan_title: plan_data}}"""
    result = {}
    for cycle_data in billing_cycles:
        cycle = cycle_data.get("cycle", "monthly")
        result[cycle] = {}
        for plan in cycle_data.get("plans", []):
            title = plan.get("title", "")
            result[cycle][title.lower()] = {
                "title": title,
                "basePrice": plan.get("basePrice", 0),
                "gst": plan.get("gst", 0),
                "totalAmount": plan.get("totalAmount", 0),
                "duration": plan.get("duration", "month"),
                "save": plan.get("save", 0),
                "posts": plan.get("posts", 0),
                "citations": plan.get("citations", 0),
                "features": plan.get("features", []),
                "paymentLink": plan.get("paymentLink", ""),
                "discount": cycle_data.get("discount", 0),
                "cycle": cycle,
                "label": cycle_data.get("label", "Monthly"),
            }
    return result


def get_plan_by_name(plan_name: str, cycle: str = "monthly") -> dict | None:
    """Get specific plan details"""
    plans = get_plans()
    cycle_plans = plans.get(cycle, plans.get("monthly", {}))
    plan_lower = plan_name.lower()
    for key, plan in cycle_plans.items():
        if plan_lower in key or key in plan_lower:
            return plan
    return None


def format_plan_message(plan: dict, session_id: str = "") -> str:
    """Format plan details as chat message with session_id in payment link"""
    features = "\n".join([f"  ✅ {f}" for f in plan.get("features", [])])
    save_text = f"\n💰 **Aap bachayenge: ₹{plan['save']}**" if plan.get("save") else ""
    discount_text = f" ({plan['discount']}% off)" if plan.get("discount") else ""

    # Add session_id to payment link
    payment_link = plan.get("paymentLink", "")
    if session_id and payment_link:
        sep = "&" if "?" in payment_link else "?"
        payment_link = f"{payment_link}{sep}session_id={session_id}"

    return (
        f"**{plan['title']}** — {plan['label']}{discount_text}\n\n"
        f"💵 Base Price: ₹{plan['basePrice']}\n"
        f"📊 GST (18%): ₹{plan['gst']}\n"
        f"💳 **Total: ₹{plan['totalAmount']}**{save_text}\n\n"
        f"📋 **Features:**\n{features}\n\n"
        f"📝 Posts: {plan['posts']} | Citations: {plan['citations']}\n\n"
        f"🔗 **Payment Link:**\n{payment_link}"
    )


def get_all_cycles_for_plan(plan_name: str) -> list:
    """Get all billing cycles for a plan"""
    plans = get_plans()
    result = []
    for cycle, cycle_plans in plans.items():
        for key, plan in cycle_plans.items():
            if plan_name.lower() in key:
                result.append(plan)
    return result


def _get_default_plans() -> dict:
    """Fallback if API fails"""
    return {
        "monthly": {
            "basic plan": {
                "title": "Basic Plan", "basePrice": 2500, "gst": 450,
                "totalAmount": 2950, "posts": 15, "citations": 5,
                "paymentLink": "https://www.limbu.ai/checkout?planKey=subscription-basic",
                "cycle": "monthly", "label": "Monthly", "save": 0, "discount": 0,
                "features": ["Review Reply System", "Magic QR Code Generation", "Insights Dashboard"]
            },
            "professional plan": {
                "title": "Professional Plan", "basePrice": 5500, "gst": 990,
                "totalAmount": 6490, "posts": 30, "citations": 12,
                "paymentLink": "https://www.limbu.ai/checkout?planKey=subscription-professional",
                "cycle": "monthly", "label": "Monthly", "save": 0, "discount": 0,
                "features": ["Review Reply Management", "Magic QR Code Generation", "Insights Dashboard"]
            },
            "premium plan": {
                "title": "Premium Plan", "basePrice": 7500, "gst": 1350,
                "totalAmount": 8850, "posts": 45, "citations": 15,
                "paymentLink": "https://www.limbu.ai/checkout?planKey=subscription-premium",
                "cycle": "monthly", "label": "Monthly", "save": 0, "discount": 0,
                "features": ["Review Reply Management", "Magic QR Code Generation", "Insights Dashboard", "Add Professional Services"]
            }
        }
    }
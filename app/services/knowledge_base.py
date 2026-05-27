"""
Qdrant Cloud Knowledge Base with Smart RAG Routing.
Only queries about plans, features, company, franchise, FAQ go to Qdrant.
Regular conversation (business search, confirmations) bypass Qdrant.
"""
import os
import re
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME = "limbu_knowledge"
EMBED_MODEL = "all-MiniLM-L6-v2"

_client = None
_encoder = None

# ── Smart Routing — which queries need Qdrant ──────────────────────
KB_TRIGGER_WORDS = {
    # Plans & pricing
    "plan", "plans", "price", "pricing", "cost", "kitna", "kitne", "rupay", "rupee",
    "basic", "professional", "premium", "monthly", "subscription", "quarterly", "yearly",
    "discount", "offer", "package", "payment",
    # Features
    "feature", "features", "magic qr", "qr code", "qr", "website", "insight",
    "review", "citation", "post", "gmb post", "seo", "keyword", "ranking",
    "health report", "health score", "social media",
    # Company info
    "limbu ai", "limbu.ai", "company", "about", "platform", "kya hai", "what is",
    "dhanda ai", "grexa", "competitor", "comparison", "vs", "difference",
    # Franchise
    "franchise", "partner", "invest", "earning", "income", "lakh", "lakhs",
    "territory", "city rights", "sub-partner", "reseller",
    # FAQ
    "faq", "question", "doubt", "samjhao", "explain", "detail", "batao",
    "kaise kaam", "how does", "how it works",
}

def _needs_rag(query: str) -> bool:
    """Smart routing — only send to Qdrant if query is about KB topics."""
    q = query.lower().strip()

    # Very short messages — don't waste Qdrant calls
    if len(q) < 5:
        return False

    # Check for KB trigger words
    for word in KB_TRIGGER_WORDS:
        if word in q:
            return True

    return False


def get_client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        _client = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=10,
            check_compatibility=False,
        )
        print(f"[KB] Qdrant Cloud connected")
    return _client


def get_encoder():
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer
        _encoder = SentenceTransformer(EMBED_MODEL)
        print(f"[KB] Encoder loaded: {EMBED_MODEL}")
    return _encoder


def search_knowledge(query: str, top_k: int = 3) -> list:
    """Search Qdrant for relevant chunks."""
    try:
        client = get_client()
        encoder = get_encoder()

        # Check collection exists
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            print(f"[KB] Collection not found — run setup_knowledge_base()")
            return []

        query_vector = encoder.encode(query).tolist()
        try:
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=top_k,
                score_threshold=0.35,
            ).points
        except Exception:
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=0.35,
            )

        return [
            {"text": r.payload.get("text", ""), "category": r.payload.get("category", ""), "score": r.score}
            for r in results
        ]
    except Exception as e:
        print(f"[KB] Search error: {e}")
        return []


def get_rag_context(query: str, top_k: int = 3) -> str:
    """
    Get RAG context ONLY if query is about KB topics.
    Returns empty string for normal conversation OR if Qdrant unavailable.
    """
    if not QDRANT_URL or not QDRANT_API_KEY:
        return ""
    if not _needs_rag(query):
        return ""
    try:
        results = search_knowledge(query, top_k=top_k)
        if not results:
            return ""
        parts = [r["text"] for r in results if r["score"] > 0.35]
        if not parts:
            return ""
        print(f"[KB] RAG: {query[:40]!r} → {len(parts)} chunks")
        return "\n\n".join(parts)
    except Exception as e:
        print(f"[KB] RAG skipped: {e}")
        return ""


# ── Knowledge Base Data ────────────────────────────────────────────
KNOWLEDGE_CHUNKS = [

    {"category": "about", "text": """Limbu AI kya hai:
Limbu AI ek AI-powered Google Business Profile (GMB) automation platform hai jo local businesses ko Google Search aur Maps mein top position dilata hai.
Automates: GMB posts, social media posting, AI video uploads, review management, review reply, website creation, local SEO, multi-location management, WhatsApp workflows, AI marketing content.
Built for: small businesses, multi-location brands, agencies, franchise partners, local service businesses.
Contact: +91 9289344726 | info@limbu.ai | limbu.ai"""},

    {"category": "plans", "text": """Limbu AI Subscription Plans (sab + 18% GST):

Basic Plan - Rs 2500/month
Best for: small businesses
- 15 GMB Posts/month
- Social media posting
- Video uploads
- 5 Business Citations
- Review Reply System
- Magic QR Code Generation
- Insights & Performance Dashboard
- Category Addition & Optimization
- Website Builder (FREE)

Professional Plan - Rs 5500/month
Best for: growing businesses
- 30 GMB Posts/month
- Social media posting
- Video uploads
- 12 Business Citations
- Review Reply Management
- Magic QR Code Generation
- Insights & Performance Dashboard
- Category Addition & Optimization
- Website Builder (FREE)

Premium Plan - Rs 7500/month (MOST POPULAR)
Best for: brands focused on automation
- 45 GMB Posts/month
- Social media posting
- Video uploads
- 15 Business Citations
- Advanced Review Reply Management
- Magic QR Code Generation
- Insights & Performance Dashboard
- Category Addition & Optimization
- Website Builder (FREE)
- Professional Services Addition (extra SEO services)

Billing Discounts: Monthly (standard) | Quarterly (10% off) | Yearly (20% off)"""},

    {"category": "plans", "text": """Plan mein kya difference hai:

Basic vs Professional vs Premium:
- GMB Posts: Basic=15, Professional=30, Premium=45 per month
- Citations: Basic=5, Professional=12, Premium=15
- Review Reply: Basic=system, Professional=management, Premium=advanced
- Professional Services: ONLY in Premium

Premium Professional Services includes:
- Business keyword research
- Service-based SEO optimization
- Professional service listing setup
- Advanced category optimization
- SEO-friendly service descriptions
- Better Google ranking optimization
- Local search visibility improvement
- Customer-focused service structuring

Recommendation:
- New business? → Basic Rs 2500
- Growing business, want more visibility? → Professional Rs 5500
- Serious about automation + max reach? → Premium Rs 7500"""},

    {"category": "plans", "text": """GMB One-time Services:

GMB Assistance & Update Plan: Rs 2500 + GST
- Profile check, website URL update, number update, corrections, 1 month support

GMB Creation & Management Plan: Rs 3000 + GST
- GMB creation from scratch, verification, categories, products, services, optimization, 1 month support

Website Development:
- Starter: Rs 9999 + GST (5 pages, basic SEO, contact form)
- Business: Rs 25000 + GST (15 pages, custom design, admin panel, analytics)
- Enterprise: Rs 48000 + GST (35 pages, e-commerce, payment gateway)

SEO Plans:
- Basic SEO: Rs 5999 (keyword research, meta tags)
- Standard SEO: Rs 9999 (backlinks, competitor analysis)
- Advanced SEO: Rs 15999 (45-page SEO, high quality backlinks, local SEO)

Ads Setup:
- Google Ads Account Setup: Rs 2500 + GST
- Meta Ads Account Setup: Rs 3500 + GST"""},

    {"category": "features", "text": """Magic QR Code System kya hai:

Magic QR ek smart review collection system hai.

Process:
1. Customer business mein aata hai
2. QR Code scan karta hai
3. Automatically AI-generated review draft appear hota hai (business keywords se)
4. Customer sirf ek click mein review post kar deta hai

Magic QR Features:
- Smart Review Filtering
- Auto-Generated Review Drafts (aapke business keywords se)
- Keyword-Optimized Reviews
- One-Click Scan & Post System
- Negative reviews reduce hoti hain
- Google ranking signals improve hote hain
- Authentic positive reviews increase hoti hain

Faayda: Customers ko khud kuch likhna nahi padta. Sirf scan karo aur post karo."""},

    {"category": "features", "text": """Limbu AI ke main features detail mein:

1. AI Post Generation:
GMB + social media posts automatically create aur publish. SEO-optimized, daily automation.
Platforms: Google Business Profile, Facebook, Instagram, LinkedIn, Pinterest

2. Review Management:
AI review replies generate karta hai. Negative review control. Reputation management.

3. Magic QR Code:
Customer scans → review draft ready → one click post.

4. Website Builder:
Free AI website included in all subscription plans.

5. Insights Dashboard:
Performance tracking, analytics, monthly reports, Google rankings.

6. Local SEO:
Business keyword research, category optimization, Google Maps visibility.

7. Social Media Management:
Facebook, Instagram, LinkedIn, Pinterest — AI posts, captions, automated publishing.

8. Multi-location Management:
Sabhi locations ek dashboard se manage karo.

9. AI Video Uploads:
AI-generated videos directly Google Business Profile mein upload.

10. WhatsApp Workflows:
Customer communication automation."""},

    {"category": "franchise", "text": """Limbu AI Franchise Program:

Investment: Rs 5,00,000 + 18% GST (ek baar, koi hidden charges nahi)
Revenue Share: 50%
Monthly Earning: Rs 1 lakh se Rs 3 lakh per month
ROI: 4-6 months mein investment recover
Time: Sirf 3-4 hours/day, ghar se kaam kar sakte ho
Technical Skills: Bilkul nahi chahiye — AI sab handle karta hai

Franchise Highlights:
- 2.5L+ monthly target potential
- 100% Recurring Revenue Model
- 250+ Businesses Scaled
- 1000+ Happy Partners
- 50+ Cities Covered
- 98% Success Rate
- 4.9/5 User Rating

Franchise mein milta hai:
- Exclusive city/territory rights
- Up to 10 sub-partners
- Unlimited users
- Complete training + dedicated support manager
- Ready-made marketing materials
- AI automation platform access
- Technical + business guidance
- Branding customization"""},

    {"category": "franchise", "text": """Franchise FAQ:

Q: Kya main ghar se kaam kar sakta hoon?
A: Haan, poora business remotely operate kar sakte ho.

Q: Technical knowledge chahiye?
A: Nahi. AI sab handle karta hai. Complete training bhi milti hai.

Q: Monthly income kitni hogi?
A: Rs 1L-3L earning potential. Effort aur sales pe depend karta hai. 98% success rate hai.

Q: Investment kab wapas milega?
A: Average 4-6 months mein.

Q: Koi hidden charges hain?
A: Nahi, sirf ek baar Rs 5L + GST. Koi hidden charges nahi.

Q: Kitne sub-partners add kar sakte hain?
A: 10 sub-partners tak.

Q: Territory exclusive hai?
A: Haan, exclusive city rights milti hain.

Q: Kya part-time kar sakte hain?
A: Haan, sirf 3-4 hours daily chahiye.

Contact: +91 9289344726 | info@limbu.ai"""},

    {"category": "comparison", "text": """Limbu AI vs Competitors:

Limbu AI vs Dhanda AI:
- Dhanda AI: basic business management tool
- Limbu AI: complete AI ecosystem
  - GMB automation + local SEO
  - Business keyword research
  - AI content + social media
  - Review automation
  - WhatsApp workflows
  - Multi-location support
  - AI video uploads

Limbu AI vs Grexa AI:
- Grexa AI: mainly CRM + WhatsApp automation focused
- Limbu AI: complete local business growth platform
  - Google Business optimization
  - Local SEO + keyword research
  - AI marketing content
  - Review management
  - Social media management (Facebook, Instagram, LinkedIn, Pinterest)
  - Multi-location dashboard
  - AI video uploads

Limbu AI unique advantages:
- Only platform with Magic QR review system
- AI video uploads to GMB
- WhatsApp workflow integration
- 50+ cities coverage
- 98% success rate
- 250+ businesses scaled"""},

    {"category": "objections", "text": """Common objections aur jawab:

"Bahut mehenga hai":
- Professional plan Rs 5500/month = Rs 183/day. Ek customer roz aaye to ROI cover.
- Yearly plan pe 20% discount milta hai.
- Pehle FREE features try karo — health report, QR, website sab free.

"Mujhe time nahi hai":
- Limbu AI poora automatically kaam karta hai — posts, reviews, sab AI handle karta hai.
- Sirf 1-2 hours setup + AI rest karta hai.

"Already someone manages my GMB":
- Kya woh daily AI posts daal rahe hain? Competitors AI se kaam kar rahe hain.
- FREE analysis karo — compare karo results.

"Results nahi dikhte":
- Google mein 3 months lagta hai. 250+ businesses ne results dekhe hain.
- Consistent AI posting se ranking improve hoti hai.

"Sochna hai / baad mein":
- Competitors abhi bhi kaam kar rahe hain. Har din delay = lost visibility.
- FREE health report se shuru karo — koi commitment nahi."""},

    {"category": "sales", "text": """Sales approach for Limbu AI:

Consultative selling steps:
1. User ka business samjho — kya problem hai?
2. FREE analysis offer karo (health report, insights)
3. Pain points identify karo — reviews, visibility, competitors
4. Relevant plan recommend karo with ROI
5. Social proof: 250+ businesses, 98% success rate
6. Urgency: competitors daily posting kar rahe hain
7. Easy next step: FREE trial se shuru karo

Best selling lines:
- "Aapke competitors daily 30-45 AI posts daal rahe hain — aap?"
- "Rs 183/day mein poora GMB management automated"
- "FREE health report se pata chalega ki aap Google par kahan ho"
- "250+ businesses Limbu AI se grow kar chuke hain"

Upsell logic:
- Basic start karo → results dikho → Professional/Premium upgrade
- Show ROI: 1 new customer/day covers Basic plan cost"""},

    {"category": "about", "text": """Limbu AI supported business types:

Gym & Fitness, Doctors & Clinics, Salons & Beauty, Restaurants & Bars,
Pest Control, Car Garages, Tours & Travel, Yoga & Wellness,
Education & Coaching, Real Estate Agents, Retail Businesses,
Agencies, Multi-location brands, Local service businesses.

Any business jo Google par dikhna chahta hai — Limbu AI unke liye hai.

Contact: +91 9289344726 | info@limbu.ai | www.limbu.ai"""},
]


def setup_knowledge_base() -> bool:
    """Initialize Qdrant collection and load knowledge chunks."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
        from sentence_transformers import SentenceTransformer

        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30, check_compatibility=False)
        encoder = SentenceTransformer(EMBED_MODEL)

        # Check if collection exists
        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in existing:
            count = client.count(COLLECTION_NAME).count
            print(f"[KB] Collection exists with {count} points — skipping setup")
            return True

        # Create collection (all-MiniLM-L6-v2 = 384 dims)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        print(f"[KB] Created collection: {COLLECTION_NAME}")

        # Encode and upload all chunks
        points = []
        for i, chunk in enumerate(KNOWLEDGE_CHUNKS):
            vector = encoder.encode(chunk["text"]).tolist()
            points.append(PointStruct(
                id=i,
                vector=vector,
                payload={"text": chunk["text"], "category": chunk["category"]}
            ))

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"[KB] Uploaded {len(points)} knowledge chunks to Qdrant Cloud")
        return True

    except Exception as e:
        print(f"[KB] Setup failed: {e}")
        return False


def rebuild_knowledge_base() -> bool:
    """Force rebuild — delete and recreate."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30, check_compatibility=False)
        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in existing:
            client.delete_collection(COLLECTION_NAME)
            print(f"[KB] Deleted old collection")
        return setup_knowledge_base()
    except Exception as e:
        print(f"[KB] Rebuild failed: {e}")
        return False
"""
Qdrant Cloud Knowledge Base with OpenAI Embeddings.
sentence-transformers ki zaroorat nahi — OpenAI text-embedding-3-small use karta hai.
Smart RAG routing — sirf relevant queries Qdrant mein jaati hain.
"""
import os
import openai

QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
COLLECTION_NAME = "limbu_knowledge"
EMBED_MODEL = "text-embedding-3-small"  # 1536 dims, fast, cheap
EMBED_DIMS = 1536

_client = None

KB_TRIGGER_WORDS = {
    # Plans & pricing
    "plan", "plans", "price", "pricing", "cost", "kitna", "kitne", "rupay", "rupee",
    "basic", "professional", "premium", "monthly", "subscription", "quarterly", "yearly",
    "discount", "offer", "package", "payment", "charge", "charges", "fees", "fee",
    "paise", "paisa", "rate", "rates", "batao", "bataiye", "bata", "btao",
    "kitne ka", "kitna hai", "how much", "kharcha", "mahina", "mahiney",
    # Features
    "feature", "features", "magic qr", "qr code", "qr", "website", "insight",
    "review", "citation", "post", "gmb", "seo", "keyword", "ranking",
    "health report", "health score", "social media", "reel", "reels", "video",
    "whatsapp", "agent", "scraper", "leads", "automation", "posting",
    # Company info
    "limbu ai", "limbu.ai", "company", "about", "platform", "kya hai", "what is",
    "dhanda ai", "grexa", "competitor", "comparison", "vs", "difference",
    "office", "head office", "address", "location", "kaha hai", "kaha he",
    "company kaha", "kahan hai", "headquarter",
    # Franchise
    "franchise", "partner", "invest", "earning", "income", "lakh", "lakhs",
    "territory", "city rights", "sub-partner", "reseller", "business opportunity",
    # FAQ / general
    "faq", "question", "doubt", "samjhao", "explain", "detail",
    "kaise kaam", "how does", "how it works", "help", "kya milega", "kya hai",
    "services", "service", "offer karte", "provide",
}


def _needs_rag(query: str) -> bool:
    q = query.lower().strip()
    if len(q) < 3:
        return False
    for word in KB_TRIGGER_WORDS:
        if word in q:
            return True
    return False


def _embed(text: str) -> list:
    """OpenAI embedding — no local model needed."""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
    )
    return response.data[0].embedding


def get_client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        _client = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=15,
            check_compatibility=False,
        )
        print("[KB] Qdrant Cloud connected")
    return _client


def search_knowledge(query: str, top_k: int = 3) -> list:
    try:
        client = get_client()
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            print("[KB] Collection not found — run rebuild-kb")
            return []

        query_vector = _embed(query)

        try:
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=top_k,
                score_threshold=0.3,
            ).points
        except Exception:
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=0.3,
            )

        return [
            {
                "text": r.payload.get("text", ""),
                "category": r.payload.get("category", ""),
                "score": round(r.score, 3),
            }
            for r in results
        ]
    except Exception as e:
        print(f"[KB] Search error: {e}")
        return []


def get_rag_context(query: str, top_k: int = 3) -> str:
    if not QDRANT_URL or not QDRANT_API_KEY or not OPENAI_API_KEY:
        return ""
    if not _needs_rag(query):
        return ""
    try:
        results = search_knowledge(query, top_k=top_k)
        if not results:
            return ""
        parts = [r["text"] for r in results if r["score"] > 0.3]
        if not parts:
            return ""
        print(f"[KB] RAG: {query[:50]!r} -> {len(parts)} chunks")
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        print(f"[KB] RAG skipped: {e}")
        return ""


# ── Full Knowledge Base Data ───────────────────────────────────────
KNOWLEDGE_CHUNKS = [

    # ── COMPANY INFO ───────────────────────────────────────────────
    {
        "category": "company",
        "text": """LIMBU AI — COMPANY INFORMATION

Limbu AI ek AI-powered Google Business Profile (GMB) automation aur digital growth platform hai jo local businesses ko Google Search aur Google Maps mein top ranking, better visibility aur more leads dilata hai.

HEAD OFFICE ADDRESS:
Limbu AI
8th Floor, Unit No. 831,
JMD Megapolis,
Gurugram, Haryana - 122018
India

CONTACT:
Phone / WhatsApp: +91 9289344726
Email: info@limbu.ai
Website: https://limbu.ai

LIMBU AI KYA AUTOMATE KARTA HAI:
- Google Business Profile (GMB) Posts
- Social Media Posting (Facebook, Instagram, LinkedIn, Pinterest)
- AI Video & Reel Uploads
- Review Management & AI Review Replies
- Website Creation (Free included)
- Local SEO Optimization
- Multi-Location Business Management
- WhatsApp Workflows & AI Chatbot
- AI Marketing Content Creation
- Citation Building
- Reputation Management
- Data Scraping (Leads)

BUILT FOR:
Small Businesses, Multi-Location Brands, Agencies, Franchise Partners,
Doctors & Clinics, Salons & Beauty, Restaurants & Cafes, Gyms & Fitness,
Real Estate, Educational Institutes, Local Service Providers

COMPANY STATS:
- 250+ Businesses Scaled
- 1000+ Happy Partners
- 50+ Cities Covered
- 98% Success Rate
- 4.9/5 User Rating"""
    },

    # ── PRICING PLANS ──────────────────────────────────────────────
    {
        "category": "plans",
        "text": """LIMBU AI SUBSCRIPTION PLANS

IMPORTANT: Sabhi plans par 18% GST extra lagti hai.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BASIC PLAN — ₹3,500/month + 18% GST
Best for: Small businesses, new businesses
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features included:
✅ 15 Google Business Profile (GMB) Posts per month
✅ 5 Business Citations
✅ Review Reply System (AI generated replies)
✅ Magic QR Code Generation
✅ Insights & Performance Dashboard
✅ Category Addition & Optimization
✅ Website Builder (Free)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROFESSIONAL PLAN — ₹5,500/month + 18% GST
Best for: Growing businesses wanting more visibility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features included:
✅ 30 Google Business Profile (GMB) Posts per month
✅ 12 Business Citations
✅ Review Reply Management (Advanced AI replies)
✅ Custom QR Code Generation
✅ Business Insights Dashboard
✅ Category Setup & Optimization
✅ Business Website Builder (Free)
✅ WhatsApp API Integration
✅ Multi-Agent Support (Up to 5 Agents)
✅ Data Scraper (1,000 Leads per month)
✅ 4 AI Generated Reels per month

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PREMIUM PLAN — ₹7,500/month + 18% GST
Best for: Maximum automation, serious brands
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features included:
✅ 45 Google Business Profile (GMB) Posts per month
✅ 20 Business Citations
✅ Advanced Review Reply Management
✅ Custom QR Code Generation
✅ Business Insights Dashboard
✅ Category Addition & Optimization
✅ Website Builder (Free)
✅ Professional Services Integration
✅ 10 Agent Access
✅ WhatsApp Workflow Automation
✅ 10 AI Generated Reels per month

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILLING DISCOUNTS:
Quarterly Payment = 10% Discount
Yearly Payment = 20% Discount

RECOMMENDATION:
New Business → Basic (₹3,500/month)
Growing Business → Professional (₹5,500/month)
Maximum Growth → Premium (₹7,500/month)"""
    },

    # ── PLAN COMPARISON ────────────────────────────────────────────
    {
        "category": "plans",
        "text": """PLAN COMPARISON — BASIC vs PROFESSIONAL vs PREMIUM

GMB Posts per month:
- Basic: 15 posts
- Professional: 30 posts
- Premium: 45 posts

Business Citations:
- Basic: 5 citations
- Professional: 12 citations
- Premium: 20 citations

Review Management:
- Basic: Review Reply System
- Professional: Review Reply Management
- Premium: Advanced Review Reply Management

QR Code:
- Basic: Magic QR Code
- Professional: Custom QR Code
- Premium: Custom QR Code

Website Builder:
- All 3 plans mein FREE included

WhatsApp Integration:
- Basic: Not included
- Professional: WhatsApp API Integration (5 agents)
- Premium: WhatsApp Workflow Automation (10 agents)

AI Reels/Videos:
- Basic: Not included
- Professional: 4 AI Reels per month
- Premium: 10 AI Reels per month

Data Scraper / Leads:
- Basic: Not included
- Professional: 1,000 Leads per month
- Premium: Included

Professional Services:
- Basic: Not included
- Professional: Not included
- Premium: Professional Services Integration

PRICES:
Basic = ₹3,500/month
Professional = ₹5,500/month
Premium = ₹7,500/month
(All + 18% GST | Quarterly 10% off | Yearly 20% off)"""
    },

    # ── ONE-TIME SERVICES ──────────────────────────────────────────
    {
        "category": "services",
        "text": """LIMBU AI ONE-TIME SERVICES

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GMB SERVICES (One-time)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GMB Assistance & Update Plan — ₹2,500 + GST
Includes:
- Google Business Profile functionality check
- Website URL update
- Mobile number update
- Basic profile verification check
- Minor corrections
- 1 Month support

GMB Creation & Management Plan — ₹3,000 + GST
Includes:
- GMB creation from scratch
- Address verification guidance
- Category selection
- Product listing setup
- Service management
- Business optimization
- 1 Month support

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WEBSITE DEVELOPMENT (One-time)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starter Website — ₹9,999 + GST (Total: ₹11,799)
- 5 Professional Pages
- Responsive Design
- Basic SEO Setup
- Contact Form
- Social Media Integration
- 1 Month Support

Business Website — ₹25,000 + GST (Total: ₹29,500)
- 15 Professional Pages
- Custom UI/UX Design
- Advanced SEO
- Admin Panel
- Google Analytics
- 3 Months Support

Enterprise Website — ₹48,000 + GST (Total: ₹56,640)
- 35 Professional Pages
- Fully Custom Design
- E-commerce Integration
- Payment Gateway
- Advanced Security
- 6 Months Support

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEO PLANS (Monthly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Basic SEO — ₹5,999/month
- 5-7 Target Keywords
- Keyword Research
- Meta Tags Optimization
- Basic Technical SEO
- Monthly Report

Standard SEO — ₹9,999/month
- 15 Target Keywords
- Technical SEO Audit
- Backlink Building
- Competitor Analysis
- Bi-Weekly Reports
- 4 SEO Friendly Blogs

Advanced SEO — ₹15,999/month
- 25 Target Keywords
- 10 SEO Friendly Blogs
- Complete SEO Strategy
- High Quality Backlinks
- Technical Optimization
- Local SEO
- Weekly Reports

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADS ACCOUNT SETUP (One-time)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Google Ads Account Setup — ₹2,500 + GST
- Account creation
- Billing configuration
- Keyword research
- Negative keyword setup
- GA4 setup
- Conversion tracking

Meta Ads Account Setup — ₹3,500 + GST
- Business Manager setup
- Ad account configuration
- Audience research
- Pixel/CAPI setup
- Creative strategy
- Copywriting"""
    },

    # ── FEATURES DETAIL ────────────────────────────────────────────
    {
        "category": "features",
        "text": """LIMBU AI KEY FEATURES IN DETAIL

1. AI POST GENERATION
- GMB + social media posts automatically create aur publish karta hai
- SEO-optimized content with trending keywords
- Daily automation — manually kuch nahi karna
- Platforms: Google Business Profile, Facebook, Instagram, LinkedIn, Pinterest
- Basic: 15 posts | Professional: 30 posts | Premium: 45 posts per month

2. REVIEW MANAGEMENT
- AI automatically customer reviews ka reply generate karta hai
- Negative review control aur management
- Reputation management
- Fast response automation
- Customer engagement improvement

3. MAGIC QR CODE (Basic) / CUSTOM QR CODE (Pro & Premium)
- Customer QR scan karta hai
- AI automatically review draft generate karta hai (business keywords se)
- Customer ek click mein Google review post kar deta hai
- Smart Review Filtering
- Keyword-Optimized Reviews
- Increases positive reviews
- Improves Google ranking signals

4. FREE WEBSITE BUILDER
- Sabhi plans mein free AI website included hai
- Responsive design, mobile-friendly
- SEO optimized
- Business-focused landing page

5. INSIGHTS & PERFORMANCE DASHBOARD
- Google Business Profile performance tracking
- Monthly analytics reports
- Google ranking visibility
- Customer engagement metrics

6. LOCAL SEO OPTIMIZATION
- Business keyword research
- Category addition & optimization
- Google Maps visibility improvement
- Local search ranking improvement

7. SOCIAL MEDIA MANAGEMENT
- Facebook, Instagram, LinkedIn, Pinterest — automated AI posts
- SEO-focused captions
- Promotional content generation
- Branding consistency

8. MULTI-LOCATION MANAGEMENT
- Sabhi locations ek dashboard se manage karo
- Chain restaurants, salons, clinics ke liye perfect

9. AI VIDEO & REELS
- Professional: 4 AI reels/month
- Premium: 10 AI reels/month
- GMB aur social media ke liye AI-generated videos

10. WHATSAPP INTEGRATION
- Professional: WhatsApp API Integration (5 agents)
- Premium: WhatsApp Workflow Automation (10 agents)
- Customer communication automation

11. DATA SCRAPER
- Professional & Premium: 1,000 leads/month
- Business lead generation
- Local market data extraction

12. CITATION BUILDING
- Basic: 5 citations | Professional: 12 | Premium: 20
- Online directory listings
- Local SEO signals improvement"""
    },

    # ── FRANCHISE ──────────────────────────────────────────────────
    {
        "category": "franchise",
        "text": """LIMBU AI FRANCHISE PROGRAM

INVESTMENT:
Fee: ₹5,00,000 + 18% GST
Payment Type: One-time only
Hidden Charges: ZERO — koi hidden charges nahi

EARNING POTENTIAL:
Revenue Share: 50%
Monthly Earning: ₹1 lakh to ₹3 lakh per month
Monthly Target Potential: ₹2.5 lakh+
Business Model: 100% Recurring Revenue (monthly subscriptions)

INVESTMENT RECOVERY:
Average ROI: 4-6 months

TIME REQUIRED:
3-4 hours per day
Work from home — anywhere se kaam kar sakte ho

TECHNICAL SKILLS:
Bilkul nahi chahiye — AI sab kuch handle karta hai
Complete training aur support milti hai

WHAT YOU GET IN FRANCHISE:
✅ Exclusive city/territory rights
✅ Up to 10 sub-partners add kar sakte ho
✅ Unlimited users access
✅ Complete personal training
✅ Dedicated support manager
✅ Ready-made marketing materials
✅ AI-powered automation platform access
✅ Technical support
✅ Business guidance
✅ Branding customization options

FRANCHISE HIGHLIGHTS:
- 250+ Businesses Scaled
- 1000+ Happy Partners
- 50+ Cities Already Covered
- 98% Success Rate
- 4.9/5 User Rating

WHO SHOULD JOIN:
Marketing agencies, freelancers, entrepreneurs, consultants,
digital marketers, sales professionals, anyone wanting recurring income

CONTACT:
Phone/WhatsApp: +91 9289344726
Email: info@limbu.ai"""
    },

    # ── FRANCHISE FAQ ──────────────────────────────────────────────
    {
        "category": "franchise",
        "text": """FRANCHISE FAQ — COMMON QUESTIONS

Q: Ghar se kaam kar sakte hain?
A: Haan, poora business remotely operate kar sakte ho. Work from home possible hai.

Q: Technical knowledge chahiye?
A: Bilkul nahi. AI sab kuch handle karta hai — posting, replies, reports sab automatic. Complete training bhi milti hai.

Q: Monthly income kitni hogi?
A: ₹1 lakh to ₹3 lakh per month earning potential hai. Effort aur sales pe depend karta hai. 98% success rate hai.

Q: Investment kab wapas milega?
A: Average 4-6 months mein investment recover ho jaati hai.

Q: Hidden charges hain?
A: Nahi. Sirf ek baar ₹5 lakh + 18% GST. Koi hidden charges nahi.

Q: Kitne sub-partners add kar sakte hain?
A: 10 sub-partners tak add kar sakte ho franchise mein.

Q: Territory exclusive hai?
A: Haan, exclusive city aur territory rights milti hain.

Q: Part-time kar sakte hain?
A: Haan, sirf 3-4 hours daily — part-time bhi perfectly chalata hai.

Q: Kya qualification chahiye?
A: Koi specific qualification nahi. Sales mindset aur local business network helpful hai.

Q: Kitne clients se start karna chahiye?
A: 10-15 clients se comfortable income shuru ho jaati hai.

Q: Company support kab tak milegi?
A: Dedicated support manager permanently assigned hota hai.

Contact: +91 9289344726 | info@limbu.ai"""
    },

    # ── COMPETITOR COMPARISON ──────────────────────────────────────
    {
        "category": "comparison",
        "text": """LIMBU AI vs COMPETITORS

LIMBU AI vs DHANDA AI:

Dhanda AI:
- Basic business management tool
- Limited GMB features
- No AI automation
- No keyword research
- No social media management
- No multi-location support

Limbu AI:
- Complete AI ecosystem
- Full GMB automation
- AI post generation + social media
- Business keyword research
- Review automation + Magic QR
- WhatsApp workflows
- Multi-location management
- AI video/reel uploads
- Data scraper (1000 leads/month)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LIMBU AI vs GREXA AI:

Grexa AI:
- Mainly CRM + WhatsApp automation
- Basic GMB features
- Limited Google optimization
- No AI content generation
- No Magic QR

Limbu AI:
- Complete local business growth platform
- Google Business optimization + Local SEO
- AI marketing content creation
- Magic QR review system (unique)
- Social media management (Facebook, Instagram, LinkedIn, Pinterest)
- Multi-location dashboard
- AI video uploads to GMB
- Data scraper for leads

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LIMBU AI UNIQUE ADVANTAGES:
✅ Only platform with Magic QR review system
✅ AI video/reel uploads directly to GMB
✅ WhatsApp workflow + AI chatbot integration
✅ Data scraper (1000 leads/month)
✅ Multi-location management in one dashboard
✅ 50+ cities coverage
✅ 98% success rate
✅ 250+ businesses already scaled"""
    },

    # ── OBJECTION HANDLING ──────────────────────────────────────────
    {
        "category": "objections",
        "text": """OBJECTION HANDLING — COMMON CONCERNS

"Bahut mehenga hai / costly hai":
- Basic Plan sirf ₹3,500/month = ₹117/day. Ek customer roz aaye to ROI cover.
- Yearly plan pe 20% discount milti hai (₹8,400 bachenge Basic pe)
- Quarterly pe 10% off milta hai
- Pehle FREE features try karo — Health Report, QR, Website — zero commitment
- ROI: ek extra customer/day = plan ka cost cover

"Mujhe time nahi hai":
- Limbu AI poora automatically kaam karta hai
- Posts, reviews, reports — sab AI handle karta hai
- Aapko kuch nahi karna after setup
- Sirf 1-2 hours initial setup, phir AI kaam karta hai

"Already koi manage karta hai":
- Kya woh daily AI posts daal rahe hain? (Basic: 15/month, Pro: 30/month, Premium: 45/month)
- Kya woh Magic QR se reviews collect kar rahe hain?
- FREE analysis karo — compare karo results
- AI se vs manually managed — results mein fark clearly dikhta hai

"Results nahi dikhte":
- Google ranking mein 2-3 months lagta hai — yeh normal hai
- 250+ businesses ne results dekhe hain Limbu AI se
- Consistent AI posting se ranking consistently improve hoti hai
- FREE Health Report se current status dekho

"Sochna hai / baad mein dekhenge":
- Competitors abhi bhi daily kaam kar rahe hain
- Har din delay = lost Google visibility
- FREE health report se shuru karo — koi commitment nahi
- Sirf business naam batao — analysis free mein hogi"""
    },

    # ── SALES / PITCH ───────────────────────────────────────────────
    {
        "category": "sales",
        "text": """LIMBU AI SALES APPROACH & KEY POINTS

CONSULTATIVE SELLING STEPS:
1. Business type samjho — kya problem hai?
2. FREE analysis offer karo
3. Pain points identify karo (reviews, ranking, competitors)
4. Relevant plan recommend karo with ROI
5. Social proof: 250+ businesses, 98% success rate
6. Urgency: competitors daily posting kar rahe hain
7. Easy start: FREE health report se shuru karo

BUSINESS TYPE → BEST PLAN:
- New/Small business → Basic ₹3,500
- Restaurant/Salon/Clinic (single location) → Basic or Professional
- Growing business (multiple locations) → Professional ₹5,500
- Agency/Multi-location brand → Premium ₹7,500
- WhatsApp automation chahiye → Professional ₹5,500
- AI reels chahiye → Professional or Premium

ROI EXAMPLES:
- Basic ₹3,500/month = ₹117/day
- Restaurant: 1 extra table/day = ₹500+ revenue = ROI covered
- Clinic: 1 extra patient/day = ₹500-1000+ = ROI covered
- Salon: 2 extra customers/week = ROI covered

KEY SELLING LINES:
- "Aapke competitors daily 30-45 AI posts daal rahe hain — aap?"
- "₹117/day mein poora GMB management automated"
- "FREE health report se pata chalega — aap Google par kahan ho"
- "250+ businesses Limbu AI se grow kar chuke hain"
- "Magic QR se customers khud reviews denge — bina maange"

UPSELL LOGIC:
- Basic → results dikho → Professional upgrade (WhatsApp + reels)
- Professional → scale karo → Premium upgrade (more agents + automation)"""
    },

    # ── SUPPORTED BUSINESSES ───────────────────────────────────────
    {
        "category": "about",
        "text": """LIMBU AI — SUPPORTED BUSINESS TYPES

Limbu AI kisi bhi local business ke liye kaam karta hai jo Google par dikhna chahta hai.

BEST SUITED FOR:
✅ Doctors & Medical Clinics
✅ Salons, Parlours & Beauty Centers
✅ Restaurants, Cafes & Dhabas
✅ Gyms & Fitness Centers
✅ Real Estate Agents & Builders
✅ Educational Institutes & Coaching Centers
✅ Retail Shops & Stores
✅ Pest Control Services
✅ Car Garages & Mechanics
✅ Tours & Travel Agencies
✅ Yoga & Wellness Centers
✅ Handyman & Home Services
✅ Marketing Agencies
✅ Multi-Location Brands
✅ Local Service Providers
✅ Franchise Businesses

CONTACT:
Phone/WhatsApp: +91 9289344726
Email: info@limbu.ai
Website: www.limbu.ai"""
    },
]


def setup_knowledge_base() -> bool:
    """Initialize Qdrant collection with OpenAI embeddings."""
    if not QDRANT_URL or not QDRANT_API_KEY or not OPENAI_API_KEY:
        print("[KB] Missing env vars (QDRANT_URL / QDRANT_API_KEY / OPENAI_API_KEY)")
        return False
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct

        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30, check_compatibility=False)

        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in existing:
            count = client.count(COLLECTION_NAME).count
            print(f"[KB] Collection exists with {count} points — skipping setup")
            return True

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIMS, distance=Distance.COSINE),
        )
        print(f"[KB] Created collection: {COLLECTION_NAME} (dims={EMBED_DIMS})")

        points = []
        for i, chunk in enumerate(KNOWLEDGE_CHUNKS):
            print(f"[KB] Embedding chunk {i+1}/{len(KNOWLEDGE_CHUNKS)}: {chunk['category']}")
            vector = _embed(chunk["text"])
            points.append(PointStruct(
                id=i,
                vector=vector,
                payload={"text": chunk["text"], "category": chunk["category"]}
            ))

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"[KB] Uploaded {len(points)} chunks to Qdrant Cloud (OpenAI embeddings)")
        return True

    except Exception as e:
        print(f"[KB] Setup failed: {e}")
        return False


def rebuild_knowledge_base() -> bool:
    """Force rebuild — delete collection and recreate with new data."""
    if not QDRANT_URL or not QDRANT_API_KEY:
        print("[KB] Missing QDRANT_URL or QDRANT_API_KEY")
        return False
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30, check_compatibility=False)
        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in existing:
            client.delete_collection(COLLECTION_NAME)
            print("[KB] Deleted old collection")
        return setup_knowledge_base()
    except Exception as e:
        print(f"[KB] Rebuild failed: {e}")
        return False
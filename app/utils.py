def load_data():
    return [
        # About
        {"id": 1, "text": "Limbu.ai ek AI-powered local marketing platform hai jo Google Business Profile, Facebook, aur Instagram automate karta hai aur local SEO improve karta hai.", "type": "about"},
        {"id": 2, "text": "Limbu.ai local businesses ki 'near me' Google ranking improve karta hai, social media automate karta hai, aur leads generate karta hai.", "type": "about"},

        # Features
        {"id": 3, "text": "AI Post Generation: AI automatically captions, hashtags, aur SEO-optimized content banata hai jo user review karke publish kar sakta hai.", "type": "feature"},
        {"id": 4, "text": "Smart Scheduling: Posts automatically best time pe multiple platforms pe publish hoti hain.", "type": "feature"},
        {"id": 5, "text": "Review Management: AI customer reviews ka reply suggest karta hai jo edit ya turant send kiya ja sakta hai.", "type": "feature"},
        {"id": 6, "text": "Magic QR: Negative reviews filter karta hai aur private feedback collect karta hai taaki public rating improve ho.", "type": "feature"},
        {"id": 7, "text": "Dashboard: Multiple business locations manage karo aur performance insights ek jagah dekho.", "type": "feature"},

        # Pricing — Monthly Plans
        {"id": 8, "text": "Basic Plan: Rs 2500 per month. Includes: 15 GMB posts, 5 citations, review reply system, Magic QR. Best for small businesses.", "type": "pricing"},
        {"id": 9, "text": "Professional Plan: Rs 5500 per month. Includes: 30 GMB posts, 12 citations, review management, insights dashboard. Best for growing businesses.", "type": "pricing"},
        {"id": 10, "text": "Premium Plan: Rs 7500 per month. Includes: 45 GMB posts, 15 citations, advanced automation. Best for established businesses.", "type": "pricing"},

        # Pricing — One-time
        {"id": 11, "text": "GMB Assistance Plan: Rs 2500 one-time. Google Business Profile management support.", "type": "pricing"},
        {"id": 12, "text": "GMB Creation Plan: Rs 3000 one-time. Naya Google Business Profile banana.", "type": "pricing"},

        # Pricing — Website
        {"id": 13, "text": "Starter Website: Rs 9999 one-time. 5-page website.", "type": "pricing"},
        {"id": 14, "text": "Business Website: Rs 25000 one-time. 15-page professional website.", "type": "pricing"},
        {"id": 15, "text": "Enterprise Website: Rs 48000 one-time. 35 pages with eCommerce functionality.", "type": "pricing"},

        # Pricing — SEO
        {"id": 16, "text": "Basic SEO Plan: Rs 5999 per month. SEO optimization services.", "type": "pricing"},
        {"id": 17, "text": "Standard SEO Plan: Rs 9999 per month. Advanced SEO services.", "type": "pricing"},
        {"id": 18, "text": "Advanced SEO Plan: Rs 15999 per month. High-level SEO optimization.", "type": "pricing"},

        # Pricing — Ads
        {"id": 19, "text": "Google Ads Setup: Rs 2500 one-time. Meta Ads Setup: Rs 3500 one-time.", "type": "pricing"},

        # How-to
        {"id": 20, "text": "Login kaise karein: Mobile number daalo, OTP receive karo, verify karo, dashboard access milega.", "type": "how_to"},
        {"id": 21, "text": "Post kaise banayein: Post Management mein jaao, business select karo, AI se post generate karo, publish ya schedule karo.", "type": "how_to"},
        {"id": 22, "text": "Account connect kaise karein: Settings mein jaao, Connect Accounts click karo, Google ya Facebook se login karo.", "type": "how_to"},

        # Issues
        {"id": 23, "text": "OTP nahi aaya: Network check karo, number verify karo, Resend OTP use karo.", "type": "issue"},

        # FAQ
        {"id": 24, "text": "Limbu.ai secure OAuth use karta hai aur user passwords store nahi karta.", "type": "faq"},
        {"id": 25, "text": "Ek dashboard se multiple business locations manage ho sakti hain.", "type": "faq"},
        {"id": 26, "text": "AI content generate karta hai jo user edit aur approve kar sakta hai.", "type": "faq"},
        {"id": 27, "text": "Results 2 se 4 weeks mein dikhayi dene lagte hain.", "type": "faq"},
        {"id": 28, "text": "Platform beginner-friendly hai, koi technical skill nahi chahiye.", "type": "faq"},
        {"id": 29, "text": "Posts advance mein schedule ki ja sakti hain.", "type": "faq"},
        {"id": 30, "text": "Limbu.ai Facebook aur Instagram dono support karta hai.", "type": "faq"},
        {"id": 31, "text": "User AI-generated content publish se pehle edit kar sakta hai.", "type": "faq"},
        {"id": 32, "text": "Regular activity se Google rankings improve hoti hain.", "type": "faq"},
        {"id": 33, "text": "Limited free trial available hai.", "type": "faq"},
        {"id": 34, "text": "Platform restaurants, salons, clinics, gyms, aur doosre local businesses ke liye suitable hai.", "type": "faq"},
        {"id": 35, "text": "Performance analytics aur insights dashboard mein available hain.", "type": "faq"},
        {"id": 36, "text": "Team collaboration supported hai.", "type": "faq"},
        {"id": 37, "text": "Setup mein 15 se 30 minutes lagte hain. Onboarding tutorials available hain.", "type": "faq"},
        {"id": 38, "text": "User kisi bhi time plan cancel kar sakta hai, koi long-term contract nahi.", "type": "faq"},
        {"id": 39, "text": "Support chat, call, aur email se available hai.", "type": "faq"},
        {"id": 40, "text": "User data enterprise-level security se protect hai.", "type": "faq"},

        # Franchise
        {"id": 41, "text": "Franchise investment: Rs 5,00,000. Earning potential: Rs 1,00,000 se Rs 3,00,000 per month. Benefits: recurring income, 60-70% margins, exclusive city rights.", "type": "franchise"},

        # Contact
        {"id": 42, "text": "Contact: Phone 9283344726, Email info@limbu.ai, Location Gurugram India.", "type": "contact"},

        # Sales hooks — for better retrieval on business growth queries
        {"id": 43, "text": "Agar aapki GMB profile already hai toh Limbu.ai se use automate karo. AI daily posts generate karega, reviews manage karega, aur near me ranking improve hogi.", "type": "sales"},
        {"id": 44, "text": "Restaurant, dhaba, ya food business ke liye Limbu.ai bahut effective hai. Local SEO aur Google posts se near me searches mein top rank milta hai.", "type": "sales"},
        {"id": 45, "text": "Salon, clinic, gym, ya koi bhi local service business Limbu.ai se grow kar sakta hai. Social media automation aur review management se customer trust badhta hai.", "type": "sales"},
        {"id": 46, "text": "Limbu.ai se business connect karne ke steps: GMB profile connect karo, Facebook aur Instagram connect karo, phir AI automatically content banayega aur post karega.", "type": "sales"},
        {"id": 47, "text": "Naye business ke liye Basic Plan Rs 2500/month best hai. Established business ke liye Professional Plan Rs 5500/month ya Premium Plan Rs 7500/month recommended hai.", "type": "sales"},
    ]
"""Who a person is, and the one-tap answers that fit their field.

The create page offers four groups of chips (what they are working on, what they
can help with, who they want to meet, what they love talking about). A marketer
should not be shown "Rust" and "CRDTs", so the synthesis step first decides which
persona the evidence points to, and the page swaps in that persona's labels.

`VOCAB_JSON` is the same data the page renders from
(apps/cards-web/src/app/(site)/create/chips.ts); chips.test.ts fails when the two
drift apart. A suggestion that reuses one of these labels lands pre-selected on
that chip; anything else shows up as a custom chip.
"""
import json

DEFAULT_PERSONA = "general"

# id -> what the model is told it means
PERSONAS: dict[str, str] = {
    "engineering": "software, data, ML, security or infrastructure engineer",
    "founder": "founder, executive or operator building or running a company",
    "product_design": "product manager, designer or other maker of product and visual work",
    "marketing_sales": "marketing, growth, sales, partnerships, communications or customer success",
    "creator": "writer, journalist, podcaster, educator or other content creator",
    "research": "researcher, scientist, academic or student",
    "investor": "investor, analyst or finance professional",
    "general": "none of the above fits clearly",
}

VOCAB_JSON = """
{
  "general": {
    "working_on": ["A new venture", "A side project", "My current role", "Freelance work", "Research", "Writing", "Teaching / mentoring", "Community building", "Career change", "Looking for work", "Learning something new", "Investing"],
    "can_help_with": ["Career advice", "Introductions", "Mentoring", "Hiring", "Feedback on ideas", "Public speaking", "Writing", "Strategy", "Fundraising", "Project management", "Negotiation", "Networking"],
    "connect_with": ["Founders", "Mentors", "Collaborators", "Hiring managers", "Investors", "Customers", "Peers in my field", "Recruiters", "Students", "Advisors", "Potential co-founders", "Speakers / hosts"],
    "love_talking_about": ["Startups", "Technology", "Books", "Travel", "Design", "Health", "Personal finance", "Education", "Philosophy", "Sports", "Film / music", "Climate"]
  },
  "engineering": {
    "working_on": ["Building a startup", "Building with AI", "Open source", "A side project", "Developer tools", "Infrastructure / platform", "Data / ML systems", "Mobile apps", "Security", "Research engineering", "Indie hacking", "At a company"],
    "can_help_with": ["Code review", "System design", "ML / AI", "Cloud / infra", "Data / analytics", "Security", "Technical interviews", "Open source", "Architecture", "Performance", "Mobile", "DevOps"],
    "connect_with": ["Engineers", "ML researchers", "Founders", "Open-source maintainers", "Potential co-founders", "Engineering managers", "DevRel", "Recruiters", "Investors", "Security folks", "Mentors", "Hardware / robotics people"],
    "love_talking_about": ["AI / ML", "Agentic AI", "Developer tools", "Open source", "Distributed systems", "Startups", "Web3 / crypto", "Robotics", "Hardware", "Programming languages", "Engineering culture", "Security"]
  },
  "founder": {
    "working_on": ["Building a startup", "Raising funding", "Finding first customers", "Scaling a team", "B2B SaaS", "A consumer product", "A marketplace", "Hiring", "Going to market", "Looking for a co-founder", "Exploring ideas", "Running an agency / studio"],
    "can_help_with": ["Fundraising", "Pitching / storytelling", "Hiring", "Go-to-market", "Pricing", "First customers", "Team building", "Operations", "Product strategy", "Investor intros", "Company building", "Managing teams"],
    "connect_with": ["Investors", "Founders", "Potential co-founders", "Customers", "Operators", "Advisors", "Mentors", "Recruiters", "Partners", "Press", "Engineers", "Designers"],
    "love_talking_about": ["Startups", "Fundraising", "Product-market fit", "Hiring", "Leadership", "SaaS", "AI", "Climate tech", "Consumer products", "Sales", "Company culture", "Strategy"]
  },
  "product_design": {
    "working_on": ["Shipping a product", "Product strategy", "Design systems", "Brand identity", "UX research", "Mobile / app design", "Prototyping", "Design leadership", "Freelance design", "A portfolio refresh", "Zero-to-one products", "Accessibility"],
    "can_help_with": ["Product strategy", "UX / UI design", "Design systems", "User research", "Prototyping", "Roadmapping", "Branding", "Portfolio reviews", "Design critique", "Accessibility", "Product discovery", "Career advice"],
    "connect_with": ["Designers", "Product managers", "Engineers", "Founders", "Researchers", "Creative directors", "Hiring managers", "Studios / agencies", "Clients", "Mentors", "Illustrators", "Brands"],
    "love_talking_about": ["Product design", "UX", "Design systems", "Typography", "Brand", "Prototyping", "AI & design", "Product strategy", "Accessibility", "Illustration", "Motion", "Creative tools"]
  },
  "marketing_sales": {
    "working_on": ["Brand strategy", "Content marketing", "Growth / demand gen", "Outbound sales", "Partnerships", "Product marketing", "Community & events", "SEO / performance", "Founder-led sales", "A launch", "Communications / PR", "Customer success"],
    "can_help_with": ["Brand strategy", "Content strategy", "Positioning / messaging", "Sales", "Go-to-market", "Growth experiments", "SEO", "Email / lifecycle", "Partnerships", "PR / comms", "Social media", "Pricing"],
    "connect_with": ["Founders", "Marketers", "Sales leaders", "Clients", "Agencies", "Partners", "Creators", "Journalists", "Product teams", "Investors", "Recruiters", "Community managers"],
    "love_talking_about": ["Brand", "Growth", "Content", "Storytelling", "Sales", "AI in marketing", "Social media", "SEO", "Community", "Startups", "Consumer behaviour", "Creator economy"]
  },
  "creator": {
    "working_on": ["A newsletter", "A book", "A podcast", "Video content", "A course / workshop", "Freelance writing", "Building an audience", "A creative project", "Journalism", "Photography / film", "Music / art", "Community"],
    "can_help_with": ["Writing / editing", "Storytelling", "Growing an audience", "Newsletters", "Podcasting", "Video production", "Public speaking", "Interviewing", "Content strategy", "Teaching / workshops", "Publishing", "Social media"],
    "connect_with": ["Editors", "Publishers", "Brands", "Other creators", "Podcast hosts", "Founders", "Collaborators", "Journalists", "Sponsors", "Mentors", "Speakers", "Agents"],
    "love_talking_about": ["Writing", "Storytelling", "Books", "Creator economy", "Media", "Newsletters", "Podcasts", "Culture", "Film / music", "Philosophy", "Technology", "Education"]
  },
  "research": {
    "working_on": ["A research paper", "Grad school", "A PhD", "Lab work", "A dataset / benchmark", "Teaching", "Grant writing", "Industry research", "Open science", "Science communication", "A thesis", "A postdoc"],
    "can_help_with": ["Research design", "Statistics / methods", "Paper feedback", "Grant writing", "Data analysis", "Academic careers", "Grad school advice", "Peer review", "Science communication", "ML / AI", "Teaching", "Literature reviews"],
    "connect_with": ["Researchers in my field", "Collaborators", "Advisors", "Students", "Industry labs", "Funders", "Engineers", "Founders", "Mentors", "Journal editors", "Policy makers", "Conference organizers"],
    "love_talking_about": ["My field", "AI / ML", "Science communication", "Open science", "Methods", "Climate", "Healthcare", "Neuroscience", "Philosophy of science", "Education", "History / science", "Policy"]
  },
  "investor": {
    "working_on": ["Sourcing deals", "Seed investing", "Angel investing", "Portfolio support", "Market research", "Building a fund", "Due diligence", "Public markets", "A venture studio", "Impact investing", "Advising founders", "Building a thesis"],
    "can_help_with": ["Fundraising", "Deal structuring", "Valuation", "Due diligence", "Market mapping", "Investor intros", "Portfolio support", "Financial modeling", "Fund operations", "Pitch feedback", "Term sheets", "Market analysis"],
    "connect_with": ["Founders", "Co-investors", "LPs", "Operators", "Advisors", "Bankers", "Fund managers", "Researchers", "Recruiters", "Mentors", "Journalists", "Domain experts"],
    "love_talking_about": ["Markets", "Venture capital", "Startups", "AI", "Climate tech", "Fintech", "Macro", "Company building", "Emerging markets", "Founder stories", "Valuation", "Personal finance"]
  }
}
"""

VOCAB: dict[str, dict[str, list[str]]] = json.loads(VOCAB_JSON)


def normalize_persona(value) -> str:
    """The persona id a model answered with, or "" when it isn't one we know."""
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return key if key in PERSONAS else ""


def prompt_section() -> str:
    """What the synthesis prompt says about personas and their preferred labels."""
    lines = [
        "",
        "Persona and preferred labels:",
        "- `persona`: the ONE id below that best describes what the person does now, judged from the evidence.",
        "  Use \"general\" when it is unclear. Never pick \"engineering\" just because they have a GitHub account.",
        "  Personas:",
        *(f"    {pid}: {desc}" for pid, desc in PERSONAS.items()),
        "- `working_on`, `can_help_with`, `connect_with` and `love_talking_about` are chosen on screen from the",
        "  labels of that persona. When one fits what the evidence shows, use it EXACTLY as written; otherwise write",
        "  your own short phrase (1-4 words) in the person's own field's vocabulary. Never pad a list with a label",
        "  the data does not support, and never suggest developer topics for someone who is not a developer.",
        "  Labels per persona:",
    ]
    for pid, groups in VOCAB.items():
        lines.append(f"  {pid}:")
        for group, labels in groups.items():
            lines.append(f"    {group}: {' | '.join(labels)}")
    return "\n".join(lines) + "\n"

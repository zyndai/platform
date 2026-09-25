"""
Seed dummy published profiles directly into Supabase.
Run AFTER the handle column migration has been applied.

Usage: python scripts/seed_profiles.py
"""
import sys
import os
import uuid
import re
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

NOW = datetime.now(timezone.utc).isoformat()

PROFILES = [
    {
        "name": "Arjun Sharma",
        "headline": "Solidity Engineer & DeFi Protocol Architect",
        "location": "Bangalore, India",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
        "links": {
            "github": "https://github.com/arjun-sharma",
            "x": "https://x.com/arjunsharma_eth",
            "linkedin": "https://linkedin.com/in/arjunsharma",
        },
        "handle_github": "arjun-sharma",
        "handle_x": "arjunsharma_eth",
        "skills": [
            {"name": "Solidity", "level": "expert", "evidence_count": 38},
            {"name": "DeFi", "level": "expert", "evidence_count": 22},
            {"name": "Foundry", "level": "advanced", "evidence_count": 15},
            {"name": "EVM", "level": "advanced", "evidence_count": 12},
            {"name": "TypeScript", "level": "intermediate", "evidence_count": 9},
        ],
        "projects": [
            {
                "name": "YieldForge Protocol",
                "description": "Automated yield optimizer across Aave, Compound, and Morpho with gas-optimized rebalancing",
                "url": "https://github.com/arjun-sharma/yieldforge",
                "source": "github",
            },
            {
                "name": "SafeEscrow",
                "description": "Trustless escrow smart contract with timelock and multi-party dispute resolution",
                "url": "https://github.com/arjun-sharma/safe-escrow",
                "source": "github",
            },
        ],
        "citation_snippet": "Solidity engineer with 4 years building DeFi protocols. Audited 12 contracts. Contributed to Uniswap v4 hooks documentation.",
        "summary": "Arjun specializes in DeFi protocol architecture and smart contract security. He has built and audited production contracts managing over $50M TVL, with a focus on gas efficiency and formal verification using Foundry.",
        "searchable_facts": [
            "Solidity expert, 4+ years DeFi",
            "audited 12 production smart contracts",
            "contributed to Uniswap v4 hooks documentation",
            "built yield optimizer on Aave and Compound",
            "based in Bangalore India",
        ],
    },
    {
        "name": "Maya Chen",
        "headline": "Full-Stack AI Engineer | Next.js · Python · LLMs",
        "location": "San Francisco, CA",
        "avatar_url": "https://avatars.githubusercontent.com/u/1234567",
        "links": {
            "github": "https://github.com/mayachen-dev",
            "x": "https://x.com/mayachenai",
            "linkedin": "https://linkedin.com/in/mayachen",
            "website": "https://mayachen.dev",
        },
        "handle_github": "mayachen-dev",
        "handle_x": "mayachenai",
        "skills": [
            {"name": "Python", "level": "expert", "evidence_count": 45},
            {"name": "Next.js", "level": "expert", "evidence_count": 31},
            {"name": "LLM integration", "level": "advanced", "evidence_count": 19},
            {"name": "FastAPI", "level": "advanced", "evidence_count": 16},
            {"name": "React", "level": "advanced", "evidence_count": 28},
            {"name": "PostgreSQL", "level": "intermediate", "evidence_count": 11},
        ],
        "projects": [
            {
                "name": "DocuChat",
                "description": "RAG-based document Q&A system using LangChain, Pinecone, and GPT-4o. Supports PDF, Notion, and Confluence sources.",
                "url": "https://github.com/mayachen-dev/docuchat",
                "source": "github",
            },
            {
                "name": "StreamAgent",
                "description": "Real-time AI agent framework with streaming tool calls and observability dashboard",
                "url": "https://github.com/mayachen-dev/streamagent",
                "source": "github",
            },
        ],
        "citation_snippet": "Full-stack AI engineer shipping LLM-powered products. Former ML engineer at Stripe. Open-source contributor to LangChain and Vercel AI SDK.",
        "summary": "Maya builds AI-native web applications from model to deployment. She contributed to LangChain's document loader ecosystem, maintains a popular Next.js AI starter, and previously shipped ML fraud detection systems at Stripe processing millions of daily transactions.",
        "searchable_facts": [
            "full-stack AI engineer, ex-Stripe ML team",
            "LangChain open-source contributor",
            "Vercel AI SDK contributor",
            "Next.js and Python expert",
            "based in San Francisco CA",
            "builds RAG and agent systems",
        ],
    },
    {
        "name": "Luka Novak",
        "headline": "Rust Systems Engineer | Solana · WebAssembly · Zero-Knowledge",
        "location": "Ljubljana, Slovenia",
        "avatar_url": "https://avatars.githubusercontent.com/u/9876543",
        "links": {
            "github": "https://github.com/lukanovak-rs",
            "x": "https://x.com/lukanovak_rs",
            "linkedin": "https://linkedin.com/in/lukanovak",
        },
        "handle_github": "lukanovak-rs",
        "handle_x": "lukanovak_rs",
        "skills": [
            {"name": "Rust", "level": "expert", "evidence_count": 52},
            {"name": "Solana", "level": "expert", "evidence_count": 24},
            {"name": "WebAssembly", "level": "advanced", "evidence_count": 18},
            {"name": "Zero-Knowledge proofs", "level": "intermediate", "evidence_count": 8},
            {"name": "C++", "level": "advanced", "evidence_count": 14},
        ],
        "projects": [
            {
                "name": "anchor-zk",
                "description": "Anchor framework extension for ZK-proof verification on Solana programs",
                "url": "https://github.com/lukanovak-rs/anchor-zk",
                "source": "github",
            },
            {
                "name": "wasm-rt",
                "description": "Minimal WebAssembly runtime in Rust, targeting embedded systems and blockchain VMs",
                "url": "https://github.com/lukanovak-rs/wasm-rt",
                "source": "github",
            },
        ],
        "citation_snippet": "Rust and Solana systems engineer. Contributor to the Solana runtime. Shipped two Anchor programs in production with 500K+ transactions.",
        "summary": "Luka writes performance-critical systems code in Rust. He has contributed to the Solana validator codebase, built an Anchor ZK extension used by 3 production programs, and maintains a lightweight WASM runtime for constrained environments.",
        "searchable_facts": [
            "Rust expert, 5+ years systems programming",
            "Solana runtime contributor",
            "Anchor and Solana programs in production",
            "WebAssembly runtime author",
            "based in Ljubljana Slovenia",
            "ZK proofs on Solana",
        ],
    },
    {
        "name": "Priya Nair",
        "headline": "Product Engineer | React · Node.js · Fintech",
        "location": "Mumbai, India",
        "avatar_url": "https://avatars.githubusercontent.com/u/2345678",
        "links": {
            "github": "https://github.com/priya-nair",
            "linkedin": "https://linkedin.com/in/priya-nair",
            "website": "https://priyanair.dev",
        },
        "handle_github": "priya-nair",
        "handle_x": None,
        "skills": [
            {"name": "React", "level": "expert", "evidence_count": 40},
            {"name": "Node.js", "level": "expert", "evidence_count": 35},
            {"name": "TypeScript", "level": "expert", "evidence_count": 42},
            {"name": "PostgreSQL", "level": "advanced", "evidence_count": 20},
            {"name": "AWS", "level": "intermediate", "evidence_count": 13},
        ],
        "projects": [
            {
                "name": "PayKit",
                "description": "Open-source payment integration library for Razorpay, Stripe, and UPI with React hooks",
                "url": "https://github.com/priya-nair/paykit",
                "source": "github",
            },
            {
                "name": "Ledger UI",
                "description": "Financial dashboard component library built on Radix UI with real-time chart updates",
                "url": "https://github.com/priya-nair/ledger-ui",
                "source": "github",
            },
        ],
        "citation_snippet": "Product engineer specializing in fintech frontend. Built payment flows used by 200K+ users. Maintains PayKit, an open-source Razorpay/Stripe integration library with 1.4K GitHub stars.",
        "summary": "Priya builds consumer-facing fintech products with React and Node.js. Her PayKit library simplifies Indian payment gateway integration and has been adopted by dozens of startups. She previously led frontend at a Mumbai-based neobank.",
        "searchable_facts": [
            "React and TypeScript expert",
            "fintech product engineer",
            "PayKit open-source library, 1.4K stars",
            "former frontend lead at Mumbai neobank",
            "Razorpay and Stripe integration specialist",
            "based in Mumbai India",
        ],
    },
    {
        "name": "Tomás Reyes",
        "headline": "DevOps & Platform Engineer | Kubernetes · Terraform · Go",
        "location": "Mexico City, Mexico",
        "avatar_url": "https://avatars.githubusercontent.com/u/3456789",
        "links": {
            "github": "https://github.com/tomas-reyes",
            "x": "https://x.com/tomas_reyes_go",
            "linkedin": "https://linkedin.com/in/tomasreyes",
        },
        "handle_github": "tomas-reyes",
        "handle_x": "tomas_reyes_go",
        "skills": [
            {"name": "Kubernetes", "level": "expert", "evidence_count": 33},
            {"name": "Terraform", "level": "expert", "evidence_count": 28},
            {"name": "Go", "level": "advanced", "evidence_count": 22},
            {"name": "AWS", "level": "advanced", "evidence_count": 25},
            {"name": "Prometheus", "level": "advanced", "evidence_count": 17},
            {"name": "Python", "level": "intermediate", "evidence_count": 10},
        ],
        "projects": [
            {
                "name": "k8s-cost-guard",
                "description": "Kubernetes operator that enforces cost budgets per namespace and auto-scales down idle workloads",
                "url": "https://github.com/tomas-reyes/k8s-cost-guard",
                "source": "github",
            },
            {
                "name": "terraform-aws-ecs-fargate",
                "description": "Production-ready Terraform module for ECS Fargate with blue-green deployment support",
                "url": "https://github.com/tomas-reyes/terraform-aws-ecs-fargate",
                "source": "github",
            },
        ],
        "citation_snippet": "Platform engineer managing 200-node Kubernetes clusters. Built internal developer platform adopted by 50+ engineers. Terraform module with 800+ GitHub stars.",
        "summary": "Tomás specializes in developer platform engineering and cloud cost optimization. He manages multi-region Kubernetes infrastructure for an e-commerce platform, built a cost enforcement operator that reduced cloud spend by 35%, and maintains a popular Terraform AWS module.",
        "searchable_facts": [
            "Kubernetes expert, 200-node cluster management",
            "Terraform AWS module, 800 GitHub stars",
            "Go systems programming",
            "cloud cost optimization specialist",
            "internal developer platform for 50+ engineers",
            "based in Mexico City Mexico",
        ],
    },
]


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:50]


def make_handle(p: dict) -> str:
    base = (
        p["handle_github"]
        or (p["handle_x"] and p["handle_x"])
        or slugify(p["name"])
    )
    return base.lower()


def build_card(p: dict) -> dict:
    card_id = str(uuid.uuid4())
    handle = make_handle(p)
    return {
        "id": card_id,
        "status": "published",
        "handle_github": p.get("handle_github"),
        "handle_x": p.get("handle_x"),
        "handle": handle,
        "card": {
            "id": card_id,
            "schema_version": "1.0",
            "status": "published",
            "handle": handle,
            "created_at": NOW,
            "updated_at": NOW,
            "identity": {
                "name": p["name"],
                "headline": p["headline"],
                "location": p["location"],
                "avatar_url": p["avatar_url"],
                "links": p["links"],
            },
            "citation_snippet": p["citation_snippet"],
            "summary": p["summary"],
            "skills": p["skills"],
            "projects": p["projects"],
            "writing_samples": [],
            "searchable_facts": p["searchable_facts"],
            "sources": [],
            "review": {
                "status": "human_approved",
                "reviewed_by": "seed_script",
                "reviewed_at": NOW,
            },
        },
    }


def main():
    sb = config.get_supabase()
    inserted = 0
    for p in PROFILES:
        row = build_card(p)
        existing = sb.table("agent_profile_cards").select("id").eq("handle", row["handle"]).execute()
        if existing.data:
            print(f"  skip {row['handle']} (already exists)")
            continue
        sb.table("agent_profile_cards").insert(row).execute()
        print(f"  created zynd.ai/p/{row['handle']}  ({p['name']})")
        inserted += 1
    print(f"\nDone. {inserted} profiles created.")


if __name__ == "__main__":
    main()

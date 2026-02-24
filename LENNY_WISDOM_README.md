# 🎙️ Lenny's Podcast Wisdom Search

A local search system for querying 303 podcast transcripts from Lenny's Podcast, featuring insights from top product leaders like Shreyas Doshi, Julie Zhuo, Marty Cagan, Brian Chesky, and 200+ more experts.

## What's Included

```
lennys-podcast-transcripts/
├── episodes/                    # 303 episode transcripts
├── index/                       # Topic-based index (80+ topics)
├── search_index/                # Pre-built BM25 search index
│   ├── chunks.json              # 6,957 searchable chunks
│   └── index.pkl                # Vocabulary & scoring data
├── rag_system.py                # Search system code
└── lenny-wisdom-skill/          # Cowork skill (for future use)
    └── SKILL.md
```

## How to Use in Future Cowork Sessions

### Option 1: Ask Me to Search (Easiest)

Just ask questions like:
- "Search Lenny's transcripts for advice on prioritization"
- "What does Shreyas Doshi say about strategy vs execution?"
- "Find insights about user research frameworks"

I'll use the search system to find and synthesize relevant insights.

### Option 2: Select the Folder

1. In Cowork, select the `lennys-podcast-transcripts` folder from your computer
2. Then ask me questions and I'll search the transcripts directly

### Option 3: Command Line (if you have Python)

```bash
cd lennys-podcast-transcripts

# Basic search
python rag_system.py query "how to prioritize roadmap"

# Interactive mode
python rag_system.py interactive
```

---

## Search Capabilities

### Query Types

| Query Type | Example |
|------------|---------|
| Topic search | "prioritization frameworks" |
| Guest-specific | "What does Julie Zhuo say about management?" |
| Problem-solving | "How to handle stakeholder disagreements" |
| Framework lookup | "DHM model Gibson Biddle" |
| Career advice | "How to grow from PM to Director" |

### Available Topics (80+)

**Core PM**: product-management, product-strategy, prioritization, roadmap, metrics, okrs
**Growth**: growth-strategy, retention, acquisition, activation, experimentation, ab-testing
**Leadership**: leadership, management, hiring, team-building, culture, feedback
**Strategy**: strategy, business-strategy, product-market-fit, competition, pricing
**Career**: career-development, career-growth, personal-development, mentorship

### Notable Guests

- **Shreyas Doshi** (Stripe, Twitter, Google) - PM craft, pre-mortems, execution vs strategy
- **Julie Zhuo** (Facebook) - Design, management, leadership transitions
- **Marty Cagan** (SVPG) - Product teams, empowered teams
- **Gibson Biddle** (Netflix) - Product strategy, DHM framework
- **Elena Verna** (Amplitude, Miro) - Growth, PLG, monetization
- **Brian Chesky** (Airbnb) - Founder mode, company culture
- **Claire Hughes Johnson** (Stripe) - Scaling organizations
- **Lenny Rachitsky** - Host, cross-episode pattern synthesis

---

## Technical Details

- **Search Algorithm**: BM25 (Okapi BM25) - same algorithm used by Elasticsearch
- **Chunk Size**: ~1,500 characters with 200-char overlap
- **Vocabulary**: 29,858 unique terms
- **Index Size**: ~15MB (pre-built, instant loading)
- **Dependencies**: Python 3.8+, PyYAML only

---

## Example Session

```
🔍 Query: How should I handle prioritization?

============================================================
Result 1 | Score: 7.753
Guest: Ravi Mehta
Episode: How to build your product strategy stack
YouTube: https://www.youtube.com/watch?v=tncs0m5pmQg
============================================================
"Strategy should come ahead of goals... decisions about the direction
of the product come and go without even really being noticed because
there's nothing to calibrate against."

============================================================
Result 2 | Score: 6.619
Guest: Ian McAllister
Episode: What it takes to become a top 1% PM
YouTube: https://www.youtube.com/watch?v=7gaPPrAd7nc
============================================================
"If we were to go back through communicating, prioritizing, and
executing... is there one tactical thing you could suggest that a PM
listening to this can do to get better..."
```

---

## Keeping It Updated

The original repo is at: https://github.com/ChatPRD/lennys-podcast-transcripts

To update with new episodes:
```bash
cd lennys-podcast-transcripts
git pull origin main
python rag_system.py build  # Rebuild index (~2 min)
```

---

Built with ❤️ for product people who want expert wisdom on demand.

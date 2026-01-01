"""
Seed script to populate initial sources.
Run with: python -m scripts.seed_sources
"""

import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal, init_db
from app.db.models import Source, SourceType


# Initial sources to seed
SOURCES = [
    # RSS Feeds - AI/ML
    {
        "name": "OpenAI Blog",
        "type": SourceType.RSS,
        "url": "https://openai.com/blog/rss/",
        "category": "ai-ml",
        "credibility_tier": 1,
    },
    {
        "name": "Google AI Blog",
        "type": SourceType.RSS,
        "url": "https://blog.google/technology/ai/rss/",
        "category": "ai-ml",
        "credibility_tier": 1,
    },
    {
        "name": "DeepMind Blog",
        "type": SourceType.RSS,
        "url": "https://deepmind.google/blog/rss.xml",
        "category": "ai-ml",
        "credibility_tier": 1,
    },
    {
        "name": "Anthropic Research",
        "type": SourceType.RSS,
        "url": "https://www.anthropic.com/research/rss.xml",
        "category": "ai-ml",
        "credibility_tier": 1,
    },

    # RSS Feeds - Tech News
    {
        "name": "TechCrunch",
        "type": SourceType.RSS,
        "url": "https://techcrunch.com/feed/",
        "category": "tech",
        "credibility_tier": 2,
    },
    {
        "name": "The Verge",
        "type": SourceType.RSS,
        "url": "https://www.theverge.com/rss/index.xml",
        "category": "tech",
        "credibility_tier": 2,
    },
    {
        "name": "Ars Technica",
        "type": SourceType.RSS,
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "tech",
        "credibility_tier": 2,
    },
    {
        "name": "Wired",
        "type": SourceType.RSS,
        "url": "https://www.wired.com/feed/rss",
        "category": "tech",
        "credibility_tier": 2,
    },

    # RSS Feeds - Security
    {
        "name": "Krebs on Security",
        "type": SourceType.RSS,
        "url": "https://krebsonsecurity.com/feed/",
        "category": "security",
        "credibility_tier": 1,
    },
    {
        "name": "Schneier on Security",
        "type": SourceType.RSS,
        "url": "https://www.schneier.com/feed/atom/",
        "category": "security",
        "credibility_tier": 1,
    },
    {
        "name": "The Hacker News",
        "type": SourceType.RSS,
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "category": "security",
        "credibility_tier": 2,
    },

    # Hacker News
    {
        "name": "Hacker News - Top",
        "type": SourceType.API_HN,
        "url": "https://news.ycombinator.com",
        "category": "tech",
        "credibility_tier": 2,
        "source_metadata": {"story_type": "top"},
    },
    {
        "name": "Hacker News - New",
        "type": SourceType.API_HN,
        "url": "https://news.ycombinator.com/newest",
        "category": "tech",
        "credibility_tier": 3,
        "source_metadata": {"story_type": "new"},
    },

    # Reddit
    {
        "name": "Reddit - r/MachineLearning",
        "type": SourceType.API_REDDIT,
        "url": "https://reddit.com/r/MachineLearning",
        "category": "ai-ml",
        "credibility_tier": 2,
        "source_metadata": {"subreddit": "MachineLearning", "sort": "hot"},
    },
    {
        "name": "Reddit - r/artificial",
        "type": SourceType.API_REDDIT,
        "url": "https://reddit.com/r/artificial",
        "category": "ai-ml",
        "credibility_tier": 3,
        "source_metadata": {"subreddit": "artificial", "sort": "hot"},
    },
    {
        "name": "Reddit - r/startups",
        "type": SourceType.API_REDDIT,
        "url": "https://reddit.com/r/startups",
        "category": "tech",
        "credibility_tier": 3,
        "source_metadata": {"subreddit": "startups", "sort": "hot"},
    },
    {
        "name": "Reddit - r/netsec",
        "type": SourceType.API_REDDIT,
        "url": "https://reddit.com/r/netsec",
        "category": "security",
        "credibility_tier": 2,
        "source_metadata": {"subreddit": "netsec", "sort": "hot"},
    },
    {
        "name": "Reddit - r/programming",
        "type": SourceType.API_REDDIT,
        "url": "https://reddit.com/r/programming",
        "category": "tech",
        "credibility_tier": 3,
        "source_metadata": {"subreddit": "programming", "sort": "hot"},
    },
]


async def seed():
    """Seed the database with initial sources."""
    await init_db()

    async with AsyncSessionLocal() as session:
        for source_data in SOURCES:
            # Check if source already exists
            result = await session.execute(
                select(Source).where(Source.name == source_data["name"])
            )
            existing = result.scalar_one_or_none()

            if not existing:
                source = Source(**source_data)
                session.add(source)
                print(f"Added: {source_data['name']}")
            else:
                print(f"Exists: {source_data['name']}")

        await session.commit()
        print(f"\nSeeding complete! {len(SOURCES)} sources configured.")


if __name__ == "__main__":
    asyncio.run(seed())

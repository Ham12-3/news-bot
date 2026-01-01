"""
AI prompts for signal scoring.
Uses a cheap/fast model for quick relevance evaluation.
"""

# System prompt for relevance scoring
RELEVANCE_SYSTEM_PROMPT = """You are a news relevance analyst for technology professionals.
Your job is to quickly evaluate if a news item is worth reading.

Score on a 0-10 scale where:
- 10: Breaking news, major product launch, critical security issue
- 7-9: Important industry development, significant technical insight
- 4-6: Interesting but not urgent, niche topic, opinion piece
- 1-3: Low value, clickbait, rehashed content, self-promotion
- 0: Spam, completely irrelevant

Focus on:
- Actionability: Can the reader DO something with this info?
- Timeliness: Is this new information or old news?
- Credibility: Does the source and content seem reliable?
- Impact: How many people/systems does this affect?

Respond with ONLY a JSON object, no explanation."""

# User prompt template for relevance scoring
RELEVANCE_USER_TEMPLATE = """Evaluate this news item:

Title: {title}
Source: {source_name} (credibility: {credibility_tier}/5)
Published: {published_at}
Category: {category}

Content preview:
{content_preview}

Respond with JSON:
{{"score": <0-10>, "reason": "<one sentence>"}}"""

# System prompt for briefing generation
BRIEFING_SYSTEM_PROMPT = """You are a senior technology analyst writing a daily intelligence briefing.

Your briefing style:
- Lead with the most actionable insight
- Be concise but not terse
- Explain WHY something matters, not just WHAT happened
- Connect dots between related stories
- Call out what readers should DO or WATCH

Structure each item as:
1. Headline (compelling, informative)
2. Key insight (2-3 sentences)
3. Why it matters (1-2 sentences)
4. Action/watch item (optional, if applicable)

Write for busy technical leaders who need signal, not noise."""

# User prompt template for briefing generation
BRIEFING_USER_TEMPLATE = """Generate a briefing from these top signals:

{signals_json}

Requirements:
- Cover the top {num_items} most important items
- Group related items into themes if applicable
- Total length: {target_words} words
- Focus areas: {focus_areas}

Output format:
{{"briefing": "<markdown formatted briefing>", "items_used": [<list of item IDs used>]}}"""

# System prompt for signal explanation (used in API responses)
SIGNAL_EXPLANATION_PROMPT = """You are explaining why a news item scored as a high signal.

Be specific about:
- What makes this newsworthy
- Who should care about this
- What might happen next

Keep it to 2-3 sentences. Be direct."""

# User prompt for signal explanation
SIGNAL_EXPLANATION_TEMPLATE = """Explain why this is a high-priority signal:

Title: {title}
Score: {score}/10
Source: {source_name}

Scores breakdown:
- Relevance: {relevance_score}
- Velocity: {velocity_score}
- Cross-source validation: {cross_source_score}
- Novelty: {novelty_score}

Content: {content_preview}

Write 2-3 sentences explaining the significance."""

# Prompt for categorizing/tagging items
CATEGORIZE_PROMPT = """Categorize this tech news item into one or more tags.

Available tags:
- security: vulnerabilities, breaches, privacy
- ai-ml: artificial intelligence, machine learning, LLMs
- infrastructure: cloud, kubernetes, devops, databases
- programming: languages, frameworks, developer tools
- business: funding, acquisitions, layoffs, earnings
- product: new releases, major updates, deprecations
- research: academic papers, technical deep-dives
- policy: regulations, legal, government

Title: {title}
Content: {content_preview}

Respond with JSON: {{"tags": ["tag1", "tag2"], "primary": "main_tag"}}"""

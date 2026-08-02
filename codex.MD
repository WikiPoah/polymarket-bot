# PolymarketBot - Codex Handoff

You are continuing development on an existing project.

Read this file before making any changes.

Do not rebuild the project.
Do not restart the architecture.
Do not remove working features.

Continue from the current state.

Development rules:
- Prefer complete file replacements when changing code.
- Do not send partial snippets unless specifically requested.
- Keep the existing architecture.
- Run tests after changes.
- Keep existing tests passing.
- Make small logical commits.
- Avoid unnecessary refactors.
- Preserve the current coding style.

---

# Project Overview

PolymarketBot is a geopolitical prediction market intelligence system.

The goal is to create a bot that:

1. Retrieves active Polymarket markets.
2. Identifies geopolitical markets.
3. Retrieves external geopolitical intelligence.
4. Classifies events.
5. Matches events against markets.
6. Evaluates trading opportunities.
7. Eventually supports trading decisions.

Current priority:

Accuracy before trading execution.

The bot should become a high precision geopolitical intelligence system, not a keyword scraper.

---

# Git Workflow

The project uses milestone commits and tags.

Workflow:

    git add .
    git commit -m "Description of changes"
    git tag v0.x.x
    git push
    git push --tags

Previous development followed this workflow.

Continue using it.

---

# Current Test Status

Latest successful test:

    30 passed in 1.84s

Command:

    python -m pytest

Tests currently passing:

    tests/test_classifier.py
    tests/test_filters.py
    tests/test_market_classifier.py
    tests/test_matcher.py
    tests/test_outcome_classifier.py
    tests/test_strategy.py

---

# Repository Structure

    PolymarketBot/

    ├── src/
    │
    │   ├── main.py
    │   ├── config.py
    │   ├── models.py
    │
    │   ├── intelligence/
    │   │
    │   │   ├── client.py
    │   │   ├── classifier.py
    │   │   ├── market_classifier.py
    │   │   ├── matcher.py
    │   │   ├── outcome_classifier.py
    │   │   ├── outcomes.py
    │   │   ├── pipeline.py
    │   │   ├── query_builder.py
    │   │   ├── scorer.py
    │   │
    │   │   ├── providers/
    │   │   │   └── gdelt.py
    │   │
    │   │   └── knowledge/
    │   │       ├── actors.py
    │   │       ├── countries.py
    │   │       ├── event_keywords.py
    │   │       └── topics.py
    │   │
    │   └── strategy/
    │       └── engine.py
    │
    └── tests/
        ├── test_classifier.py
        ├── test_filters.py
        ├── test_market_classifier.py
        ├── test_matcher.py
        ├── test_outcome_classifier.py
        └── test_strategy.py

---

# Completed Components

## Polymarket API

Implemented:

- Gamma API connection.
- Active market retrieval.
- Retry handling.
- Timeout handling.
- Error handling.

Successful output:

    Connecting to Polymarket...

    Polymarket request attempt 1/3...
    Response status: 200
    Connected successfully.

    Retrieved 25 active markets.

---

## Market Filtering

Implemented geopolitical market detection.

Detects:

- countries
- leaders
- conflicts
- organisations
- energy topics
- strategic regions

Example:

    Found 1 geopolitical markets.

---

# Market Classification

File:

    src/intelligence/market_classifier.py

Purpose:

Convert raw Polymarket markets into structured ClassifiedMarket objects.

Extracts:

- event type
- actors
- countries
- topics
- expected outcome
- region

Example market:

    Xi Jinping out before 2027?

Expected classification:

    Actor:
        Xi Jinping

    Country:
        China

    Event Type:
        LEADERSHIP

    Expected Outcome:
        LEADER_REMOVED

---

# Event Classification

File:

    src/intelligence/classifier.py

Purpose:

Convert raw intelligence events into structured geopolitical events.

Extracts:

- actors
- countries
- event type
- topics
- regions

Uses:

    src/intelligence/knowledge/

---

# Knowledge Base

Location:

    src/intelligence/knowledge/

Contains:

## actors.py

Maps aliases to canonical actors.

Examples:

    Xi Jinping
    CCP
    Donald Trump
    Vladimir Putin

## countries.py

Contains country aliases and regions.

## event_keywords.py

Maps keywords to event types.

Examples:

    resign
    removed
    ousted
    strike
    sanctions
    election

## topics.py

Contains topic mappings.

---

# GDELT Intelligence Provider

File:

    src/intelligence/providers/gdelt.py

Implemented:

- API authentication
- HTTP requests
- retries
- timeout handling
- parsing

Converts results into:

    GeoPoliticalEvent

---

# Query Builder

File:

    src/intelligence/query_builder.py

Purpose:

Create intelligence search queries from markets.

Example:

Old:

    Xi Jinping China POLITICS

Improved:

    Xi Jinping China removed resignation steps down ousted succession

---

# Outcome Classifier

File:

    src/intelligence/outcome_classifier.py

Maps events into outcomes.

Examples:

    LEADER_REMOVED
    MILITARY_ESCALATION
    ECONOMIC_POLICY
    SHIPPING_DISRUPTION

---

# Matcher

File:

    src/intelligence/matcher.py

Matches:

    ScoredEvent

against:

    ClassifiedMarket

Produces:

    TradingOpportunity

Uses:

- actor
- country
- event type
- outcome
- topics
- region

---

# Strategy Engine

File:

    src/strategy/engine.py

Evaluates trading opportunities.

---

# Current Pipeline

Flow:

    Polymarket Market
            |
            v
    MarketClassifier
            |
            v
    MarketQueryBuilder
            |
            v
    GDELT Provider
            |
            v
    EventClassifier
            |
            v
    OutcomeClassifier
            |
            v
    Relevance Filtering
            |
            v
    Scoring
            |
            v
    Matcher
            |
            v
    Strategy Engine

---

# Current Market Being Tested

Market:

    Xi Jinping out before 2027?

The market resolves YES if Xi Jinping is removed from power before the deadline.

---

# Current Query

Generated query:

    Xi Jinping China removed resignation steps down ousted succession

This was improved from:

    Xi Jinping China POLITICS

because the goal is specifically leadership change detection.

---

# Current Problem

The intelligence provider retrieves unrelated China events.

Examples:

    China’s central bank injects liquidity

    China flood emergency

    South China Sea policy

    One-China policy statements

These should not match a Xi Jinping leadership removal market.

---

# Debugging History

The issue is not:

- Polymarket API.
- Market retrieval.
- Query builder.
- Market classifier.
- Matcher.

The issue is the relevance filtering stage.

---

# Important Discovery

Previously relevance used outcome as evidence.

Problematic logic:

    event.outcome != Outcome.OTHER

This was incorrect.

The OutcomeClassifier assigns outcomes too broadly.

Example:

    China flood emergency

    Event Type:
        OTHER

    Outcome:
        SHIPPING_DISRUPTION

Because:

    Outcome != OTHER

the event incorrectly passed filtering.

This created false positives.

---

# Correct Relevance Logic

For leadership markets:

Accept only if:

1. Actor matches.

Examples:

    Xi Jinping
    CCP

OR:

2. Event is:

    EventType.LEADERSHIP

AND:

    Country matches the market

Do not use Outcome as evidence for relevance.

---

# Expected Behaviour

For:

    Xi Jinping out before 2027?

Accept:

    Xi Jinping resigns

    Xi Jinping removed

    CCP succession crisis

    Xi leadership challenge

Reject:

    China floods

    China economy

    China central bank

    South China Sea policy

    One-China diplomacy

---

# Current Files Being Debugged

Main file:

    src/intelligence/pipeline.py

Important function:

    _is_relevant()

Secondary possible issue:

    src/intelligence/outcome_classifier.py

The outcome classifier may still be too aggressive.

---

# Latest Runtime Output

Current command:

    python -m src.main

Current output:

    Retrieved 25 active markets.
    Found 1 geopolitical markets.

    Query:
    Xi Jinping China removed resignation steps down ousted succession

    Events retrieved: 16

Current issue:

    Relevant events: 5

This is too high because unrelated China events remain.

---

# Next Steps

## Step 1

Improve:

    src/intelligence/pipeline.py

Specifically:

    _is_relevant()

Goal:

Reduce irrelevant events.

Expected:

    Relevant events: 0-1

instead of:

    Relevant events: 5+

---

## Step 2

If unrelated events still survive:

Investigate:

    src/intelligence/outcome_classifier.py

Outcomes should describe events.

They should not decide relevance.

---

## Step 3

Improve GDELT precision.

Possible improvements:

- stronger actor matching
- title weighting
- summary weighting
- leadership keyword weighting
- reject generic country-only events

---

## Step 4

After intelligence quality is reliable:

Review:

    src/intelligence/matcher.py

Then:

    src/strategy/engine.py

---

# Do Not Work On Yet

Do not focus on:

- order execution
- trading API
- dashboards
- UI
- automation

until intelligence quality is reliable.

---

# Current Objective

Make this work:

    Xi Jinping market

    +

    GDELT intelligence

    =

    Only Xi leadership relevant events

The bot must ignore:

    China economic news
    China weather events
    China diplomacy
    China general policy

unless they provide genuine evidence of leadership change.

---

# Final Goal

Build a high precision geopolitical prediction market intelligence system.

Priority order:

1. Correct classification.
2. Correct relevance filtering.
3. Correct market matching.
4. Correct strategy evaluation.
5. Trading execution.

Precision before speed.
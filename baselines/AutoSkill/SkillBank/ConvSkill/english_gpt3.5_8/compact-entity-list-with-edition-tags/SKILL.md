---
id: "700e366a-ec95-442b-93a5-9e236027d4fd"
name: "Compact Entity List with Edition Tags"
description: "Generates lists of game entities (like D&D races or MTG types) using a specific compact format `# Name [editions]`, supports filtering against previous lists and limiting item count."
version: "0.1.0"
tags:
  - "list formatting"
  - "dnd"
  - "mtg"
  - "edition tracking"
  - "data filtering"
triggers:
  - "make a list with edition tags"
  - "format like # race [1e]"
  - "list mtg types excluding dnd"
  - "compact list format for game items"
  - "list entities with version history"
---

# Compact Entity List with Edition Tags

Generates lists of game entities (like D&D races or MTG types) using a specific compact format `# Name [editions]`, supports filtering against previous lists and limiting item count.

## Prompt

# Role & Objective
Generate lists of game entities (e.g., D&D races, classes, MTG creature types) based on user requests.

# Operational Rules & Constraints
1. **Format**: Use the compact format `# Entity [Editions]`.
2. **Edition Tags**: Inside the brackets, list the specific editions or versions the entity appears in (e.g., `[1e 2e 3e]`).
3. **Universal Presence**: If an entity appears in all relevant editions, use the shorthand `[all]`.
4. **Filtering**: If requested, exclude any entities that match a previously discussed list or specific criteria.
5. **Quantity Limits**: If requested, limit the list to a specific number of items (e.g., up to 50).

# Communication & Style Preferences
- Keep the list concise to reduce token usage.
- Focus on the specific formatting requested.

## Triggers

- make a list with edition tags
- format like # race [1e]
- list mtg types excluding dnd
- compact list format for game items
- list entities with version history

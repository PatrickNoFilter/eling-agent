# Memory System

Eling Agent uses a multi-layer memory architecture:

## MemoryStore

The `MemoryStore` (in `memory.py`) provides:

- **Storage** — SQLite-backed episodic memory
- **Retrieval** — BM25 (FTS5) + cosine similarity ranking
- **Persistence** — Auto-saves after each exchange

## SkillLibrary

The `SkillLibrary` (in `skills.py`) auto-discovers reusable patterns:

- After each response, the LLM decides if a skill should be saved
- Skills are retrieved alongside memories for context

## Brain (Eling Library)

The underlying `eling` library provides 8 memory layers:

1. **Buffer** — Short-term working memory
2. **Episodic** — Recent conversation history
3. **Facts** — Extracted facts with HRR encoding
4. **Knowledge** — Long-term structured knowledge
5. **Zettelkasten** — Linked atomic notes
6. **Blackbox** — Flight recorder / telemetry
7. **Continuum** — Multi-agent orchestration state
8. **Builtin** — Static instructions (MEMORY.md, USER.md)

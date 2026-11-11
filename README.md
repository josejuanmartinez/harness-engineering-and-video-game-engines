# Harness Engineering and Video Game Engines

Practice material in two parts.

- [c/](c/README.md): C++ game-engine exercises. Arena and pool allocators, generational handles, cache-friendly layouts (AoS vs SoA), an ECS sparse set, events, a fixed-timestep game loop, a scene tree, deterministic physics and a small engine prototype. [c/00_review/](c/00_review/README.md) is a refresher on core C++.
- [integrations/](integrations/): LLM agent-harness exercises in Python. Structured output, agent loops with caching and sandboxed folders, a planner/scheduler DAG, provider routing with retries, SSE streaming, MCP servers and clients, RAG over a codebase, context management, evals, guardrails, tracing and long-running agents.

C++ needs MSVC or any C++20 compiler. Python needs the packages in `integrations/requirements.txt` and API keys in `integrations/.env` (see `.env.example`).

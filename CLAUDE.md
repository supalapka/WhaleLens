# Development Guidelines

## General
1. Write concise, purposeful code — avoid redundancy and over-engineering.
2. Adhere to Clean Architecture and SOLID principles at all times.
3. Enter plan mode before implementing any feature or bugfix.
4. Do not add inline comments — code should be self-explanatory.
5. Always prefer the simplest solution that satisfies the architectural constraints in rule #2.
6. Every new feature must be covered by unit tests.
7. Do not implement anything outside the agreed scope.
8. Git commit messages must be written in natural language — no description body, no co-author trailer.

## Architecture
9. Enforce Clean Architecture layer boundaries — outer layers depend on inner, never the reverse.
10. Domain logic belongs in `models/`, external API clients in `services/checkers/`, pipeline orchestration in `services/`, HTTP layer in `main.py` and route handlers.
11. Define abstract interfaces (ABC/Protocol) before implementing them in outer layers.
12. Use Pydantic models for any concept requiring validation or strong typing.
13. Domain logic must communicate failure through domain-specific exceptions — never return None where a result is expected.

## Data Access
14. All database access must go through SQLAlchemy async sessions — the engine must not be referenced outside `database.py`.
15. Schema changes require a new Alembic migration — existing migrations must never be modified.

## Infrastructure
16. Bind configuration to `pydantic-settings` BaseSettings with startup validation — never read `os.environ` directly in services.
17. Use Python `logging` module for all logging — `print()` is prohibited.
18. All I/O must be async (httpx, asyncpg/SQLAlchemy async) — no blocking calls.

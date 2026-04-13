# State

## What Is Working
- Auth (OAuth2 + JWT), multi-tenant isolation (owner_id scoping)
- Document upload → Pinecone indexing
- Portfolio CRUD + CSV/PDF import
- Semantic caching (Redis)
- SSE streaming (nginx)
- Admin RBAC dashboard + latency metrics
- Multi-source planner (intent JSON → hardcoded SQL)
- Hebrew language support
- Intelligence Layer (7-agent, deterministic scoring)
- Data normalization (cost_basis, allocation_pct)
- ValidationAgent (5 checks, confidence downgrade)

## Known Issues
- Portfolio SQL cannot safely inject owner_id in router → routes to vector (chat_service.py independently calls fetch_portfolio_context)
- Hebrew ticker symbols (אפל) don't map reliably → document_analysis fallback
- FRED: only 4 series (CPIAUCNS, FEDFUNDS, GDP, UNRATE)
- _FILLER_RE doesn't strip Hebrew (acceptable — preserves financial terms)
- Returns/P&L never computed (cost_basis insufficient) — LLM FORBIDDEN from estimating
- dominant_sector always None (no DB data) — use dominant_ticker instead
- ValidationAgent skipped when no asset scores (correct — no scores to validate)

## Completed
- Production hardening (2026-04-05): fixed 7 bugs (numerical errors, misinterpretation, LLM override, generic responses, hallucinations, fake confidence, no validation)
- Multi-source planner: intent JSON → hardcoded SQL, 3-level fallback, Hebrew support
- Intelligence Layer: 7 agents, deterministic scoring, ValidationAgent, data normalization

## Next Steps
- Unit tests: ValidationAgent (input/output pairs), normalize_portfolio (empty, NULL, multi-currency)
- Integration test: full pipeline + mock DB
- Tune scoring thresholds from user feedback
- Cache MarketContext (global, daily, TTL 1h)
- Add sector data (dominant_sector currently None)
- Admin Dashboard upgrade
- RBAC implementation
- Audit events system
- Observability (metrics + logs)

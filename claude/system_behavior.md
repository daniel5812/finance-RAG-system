# System Behavior

## Request Flow
1. Semantic cache lookup (Redis)
2. If miss: router.py decomposes query → intent JSON
3. Validate params: normalize → FX direction → validate → build SQL
4. asyncio.gather(sql_tool, vector_store) — parallel
5. reranker.py scores chunks
6. chat_service.py fuses context
7. Intelligence Layer (7-stage pipeline)
   - Stage 0: UserProfiler (instant)
   - Stage 1 (parallel): MarketAnalyzer + AssetProfiler + PortfolioFit
   - Stage 2: ScoringEngine (deterministic)
   - Stage 3: Recommendation (deterministic action + LLM reasoning only)
   - Stage 4: _compute_pipeline_confidence (deterministic)
   - Stage 5: ValidationAgent (can only downgrade)
8. build_intelligence_context() → [NORMALIZED PORTFOLIO] + [VALIDATION]
9. build_user_message (intelligence + cite-only context)
10. security.py PII filter → OpenAI → confidence → cache + return

## Router / Planner (backend/rag/router.py)

Intent Types

| Type | Source | Params |
|---|---|---|
| fx_rate | sql | base, quote (ISO) |
| price_lookup | sql | ticker (1-5 chars) |
| macro_series | sql | series_id (FRED ID) |
| etf_holdings | sql | symbol (1-5 chars) |
| portfolio_analysis | vector | — |
| document_analysis | vector | query |
| investment_recommendation | vector | — |

Per-Plan Pipeline
1. _normalize_params: alias→ISO, keyword→FRED ID
2. _apply_fx_direction: extract currencies, enforce USD/ILS when both present
3. _validate_params: ticker regex, ISO set, FRED whitelist
4. _build_query_plan: hardcoded SQL template per type

SQL Templates
```
fx_rate: SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1
price_lookup: SELECT symbol, close, date FROM prices WHERE symbol='{ticker}' ORDER BY date DESC LIMIT 30
macro_series: SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12
etf_holdings: SELECT holding_symbol, weight FROM etf_holdings WHERE etf_symbol='{symbol}' ORDER BY weight DESC LIMIT 20
```

Router Does NOT Do
- Execute queries
- Generate dynamic SQL
- Inject owner_id into SQL
- Modify schemas.py or chat_service.py

## Fallback Chain

Level 1 (Per-Plan)
- Normalization fails → document_analysis + rewritten query
- Validation fails → document_analysis + rewritten query
- No currencies (FX) → document_analysis

Level 2 (Structured Intent Detector, JSON parse fails)
Detection order (first match wins):
1. FX keywords (שער, exchange, dollar, שקל) → SQL fx_rate
2. Macro keywords (אינפלציה, inflation, ריבית, gdp) → SQL macro_series
3. Portfolio keywords (תיק, portfolio, holdings) → vector
4. Price keywords (מניה, price, stock) → vector
5. No match → None

Level 3 (Raw Vector, last resort)
- Raw question to Pinecone

## Parameter Normalization

Currency Aliases
| Input | ISO |
|---|---|
| dollar, usd, דולר | USD |
| shekel, nis, שקל | ILS |
| euro, eur, אירו | EUR |
| pound, gbp | GBP |
| yen, jpy | JPY |
| franc, chf | CHF |
| cad | CAD |
| aud | AUD |

FX Direction (set-based, order ignored)
- USD + ILS → base=USD, quote=ILS (always)
- USD + X → base=USD, quote=X
- X only → base=USD, quote=X
- None → reject → document_analysis

Macro Mapping
| Input | FRED ID |
|---|---|
| inflation, cpi, אינפלציה | CPIAUCNS |
| interest rate, fed rate, ריבית | FEDFUNDS |
| gdp, תוצר | GDP |
| unemployment, unrate, אבטלה | UNRATE |

Validation Rules
| Type | Param | Rule |
|---|---|---|
| fx_rate | base, quote | in {USD, ILS, EUR, GBP, JPY, CHF, CAD, AUD} |
| price_lookup | ticker | ^[A-Z]{1,5}$ |
| macro_series | series_id | in {CPIAUCNS, FEDFUNDS, GDP, UNRATE} |
| etf_holdings | symbol | ^[A-Z]{1,5}$ |

Sanitization
- Strip non-alphanumeric/underscore, uppercase, cap 20 chars

Semantic Rewrite
- Strip English filler phrases
- Remove English stop words
- Hebrew passes through
- Cap 10 tokens
- Add context suffix

## Intelligence Layer

Pipeline Stages
0. UserProfiler (instant, no DB)
1. (parallel) MarketAnalyzer + AssetProfiler + PortfolioFit
2. ScoringEngine (deterministic: 0.30*market + 0.25*user + 0.20*diversify + 0.25*risk)
3. Recommendation (deterministic action + LLM reasoning)
4. _compute_pipeline_confidence (deterministic)
5. ValidationAgent (can only downgrade, runs LAST)

Agents
| Agent | Type |
|---|---|
| UserProfiler | Pure transform |
| MarketAnalyzer | DB reads: macro, fx |
| AssetProfiler | DB reads: prices, etf_holdings |
| PortfolioFit | DB reads + normalization |
| ScoringEngine | FULLY DETERMINISTIC (no LLM) |
| Recommendation | Deterministic action + LLM reasoning |
| ValidationAgent | 5 sanity checks; downgrades confidence |

Data Normalization (data_normalizer.py)
- Pure function, no DB/LLM
- normalize_portfolio(rows) → NormalizedPortfolio
- Deduplicates: newest row wins
- total_invested = SUM(quantity × cost_basis)
- allocation_pct = position_value / total_invested * 100
- data_note: returns/P&L NOT computable (needs live prices)

ValidationAgent Rules
- Check 1: All scores in [0.0, 1.0]
- Check 2: Action ↔ composite_score consistency
- Check 3: confidence=high requires asset_scores + fed_rate
- Check 4: recommendation.confidence=high requires data_coverage=full
- Check 5: allocation_pct sum 99–101%
- Downgrade: len(flags) >= 3 → low; any flags + high → medium

Context Builder
- [NORMALIZED PORTFOLIO — pre-computed, DO NOT recalculate]
- [VALIDATION] with flags + confidence_override
- Inserted before Portfolio Fit

## LLM FORBIDDEN OPERATIONS (core/prompts.py, at TOP)
1. NEVER perform arithmetic
2. NEVER invent financial figures not in intelligence block or document
3. NEVER compute returns/P&L from raw data
4. NEVER override BUY/HOLD/REDUCE/AVOID actions
5. NEVER invent confidence levels — use ONLY pipeline_confidence

System Prompt Rules
- Rule 7: NORMALIZED PORTFOLIO block authoritative — do NOT recompute
- Rule 8: VALIDATION block — acknowledge reduced confidence, use qualifiers

# Known Issues & Constraints

## Portfolio Analysis — SQL Not Executed via Planner
- **Issue**: `portfolio_analysis` cannot safely inject `owner_id` into SQL inside `router.py`
- **Status**: Intentional design decision. Routes to vector instead.
- **Why safe**: `chat_service.py` independently calls `fetch_portfolio_context(pool, owner_id)` using a parameterized query. Portfolio data reaches the LLM context regardless.
- **Do not**: Re-introduce SQL for portfolio_analysis in router.py without a safe injection mechanism.

## Hebrew Ticker Symbols
- **Issue**: Hebrew company names (e.g., "אפל" for Apple) cannot be reliably mapped to ticker symbols (`AAPL`)
- **Status**: By design. The prompt instructs the LLM: "DO NOT invent ticker symbols. Only output tickers explicitly named in the question."
- **Result**: Hebrew stock price queries without an explicit Latin ticker fall back to `document_analysis`.

## FRED Series Coverage
- **Issue**: Only 4 FRED series IDs are supported: `CPIAUCNS`, `FEDFUNDS`, `GDP`, `UNRATE`
- **Status**: Intentional. Expanding requires adding to both `_MACRO_MAP` and `_VALID_SERIES_IDS` in `router.py`, plus updating the prompt.

## `_FILLER_RE` Does Not Strip Hebrew Filler
- **Issue**: The filler phrase regex uses `\b` (ASCII word boundaries) and only covers English phrases.
- **Status**: Acceptable. Hebrew filler words are not stripped during semantic rewrite — Hebrew financial terms are preserved in full, which is the correct behavior for semantic search.

## Returns / P&L Are Never Computed
- **Issue**: Users may ask "how much did I make?" and the system cannot answer with a number.
- **Status**: Intentional and correct. `cost_basis` = average price paid per unit (per schema.sql). Computing returns requires current market price × quantity, which is NOT stored in the DB — only in live price feeds. `NormalizedPortfolio.data_note` explicitly states this. LLM is FORBIDDEN from estimating.
- **Resolution path**: Requires a live-price enrichment step in `data_normalizer.py` using `asset_prices` table; only viable once `AssetProfilerAgent` output is passed into portfolio normalization.

## `dominant_sector` Always None
- **Issue**: `PortfolioFitAnalysis.dominant_sector` is set to `None` in all cases.
- **Status**: Intentional — no sector data exists in the DB yet. `dominant_ticker` (by invested capital) is available.
- **Resolution path**: Add `sector` column to `asset_prices` or a separate `asset_metadata` table.

## ValidationAgent Skipped When No Asset Scores
- **Issue**: Validation checks 1–2 (score bounds, action consistency) are skipped when `report.asset_scores` is empty (e.g., factual queries without tickers).
- **Status**: By design. Checks 3–5 still run. The validation result will have `passed=True` for factual queries — which is correct since there are no scores to validate.

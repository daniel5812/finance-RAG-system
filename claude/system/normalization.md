# Parameter Normalization

All normalization runs in `_normalize_params` and `_apply_fx_direction` inside `router.py`.

## Currency Aliases (`_CURRENCY_ALIASES`)

| Input | ISO Code |
|---|---|
| dollar, dollars, usd, us dollar, דולר, דולרים | USD |
| shekel, shekels, nis, ils, israeli, שקל, שקלים | ILS |
| euro, euros, eur, אירו | EUR |
| pound, pounds, gbp | GBP |
| yen, jpy | JPY |
| franc, chf | CHF |
| cad, canadian dollar | CAD |
| aud, australian dollar | AUD |

## FX Direction Rules (`_apply_fx_direction`)
Currency detection uses a **set** — order in the question is ignored.

| Detected currencies | Result |
|---|---|
| USD + ILS | base=USD, quote=ILS (always) |
| USD + X | base=USD, quote=X |
| X only (no USD) | base=USD, quote=X |
| None detected | Plan rejected → document_analysis fallback |

## Macro Series Mapping (`_MACRO_MAP`)

| Input (EN/HE) | FRED Series ID |
|---|---|
| inflation, cpi, consumer price, אינפלציה, מדד המחירים | CPIAUCNS |
| interest rate, fed rate, federal funds, fedfunds, ריבית | FEDFUNDS |
| gdp, gross domestic product, תוצר, תמ"ג | GDP |
| unemployment, unrate, אבטלה | UNRATE |

Valid series IDs: `{CPIAUCNS, FEDFUNDS, GDP, UNRATE}`

## Parameter Validation Rules (`_validate_params`)

| Type | Param | Rule |
|---|---|---|
| `fx_rate` | base, quote | Must be in `{USD, ILS, EUR, GBP, JPY, CHF, CAD, AUD}` |
| `price_lookup` | ticker | `^[A-Z]{1,5}$` |
| `macro_series` | series_id | Must be in `{CPIAUCNS, FEDFUNDS, GDP, UNRATE}` |
| `etf_holdings` | symbol | `^[A-Z]{1,5}$` |
| `document_analysis` | query | Non-empty string |

## Sanitization (`_sanitize_param`)
Applied to all symbol/ticker values: strips non-alphanumeric/underscore, uppercases, caps at 20 chars.

## Semantic Rewrite (`_rewrite_for_semantic_search`)
Used when a plan is rejected and substituted with `document_analysis`.
- Strips English filler phrases (regex)
- Removes English stop words
- Hebrew text passes through unchanged — financial terms preserved
- Caps at 10 tokens
- Adds context suffix (e.g., "price performance", "exchange rate") based on rejected plan type

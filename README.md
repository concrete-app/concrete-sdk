# Concrete SDK

Two independent, hand-maintained packages shared across the Concrete project.

## Structure
- `sdks/python/` — Python package `concrete_sdk`. Currently holds `concrete_sdk.werkvertrag`,
  the deterministic Werkvertrag/Leistungsverzeichnis parser and Gemini transcription pipeline.
- `sdks/typescript/` — npm package `concrete-sdk`. Holds `ConcreteApi.Products/Prices/Coupons`,
  the Stripe product/price/coupon constants used by `forum`'s billing logic.
- `cli/` — `concrete-cli`, a separate standalone developer CLI.

## Publishing
- Python: `cd sdks/python && python -m build && twine upload dist/*`
- TypeScript: `cd sdks/typescript && npm run build && npm publish`

# Planning Feature Build Log

This running log tracks each development phase for the OpenSkagit planning experience. Update the relevant section after every phase.

## Phase 1 – Parcel Orientation (Planning Preview)

### Algorithms & Calculations
- Deterministic development form classification lives in `planning/views.py`. It inspects zoning signals (`ParcelPlanningFacts.zoning_general_class`, allowed-use booleans), assessor traits (`MasterParcel.land_use_code`, `flag_multi_structure`, acreage, living area), and water/septic hints to map parcels into `SHED`, `MOBILE`, `SFR`, `MULTI`, `COMMERCIAL_PLUS`, or `UNKNOWN`.
- Confidence tiers derive from the strength of the signal that produced the form (zoning metadata → HIGH, heuristics → MEDIUM, fallback → LOW). Unknown classifications always downgrade to LOW.
- Constraint extraction surfaces only material GIS flags: FEMA SFHA / floodway, shoreline jurisdiction, slope over 30%, missing utilities, and uncertain access; each emits a severity pill for the UI.
- Orientation LLM prompt (stored in `PROMPTS["orientation_system"]` and `PROMPTS["orientation_user_template"]`) receives parcel identifier, jurisdiction, lot size, deterministic development form, confidence, zoning class, utilities, and constraint booleans. The response is capped at 1–2 declarative sentences; temperature is locked at 0.2 to maintain determinism.
- Fallback copy uses predefined summaries per development form so the UI still renders when the OpenAI call fails or credentials are missing.
- Parcel search autocomplete reuses HTMX to query the `Parcel` table (optimized for lookups) with prefix/contains filters and returns cached HTML snippets for five minutes to keep the typing experience instant.
- Orientation payloads (deterministic signals + LLM text) are cached per parcel number for 15 minutes to avoid repeated heuristics/LLM calls during exploration.

### Database Connections
- `MasterParcel` provides canonical parcel identity, acreage, assessor attributes, and roll-up counts.
- `ParcelPlanningFacts` supplies zoning class, utility availability, slope, shoreline/flood indicators, and related jurisdiction metadata.
- `ParcelGeometry` fills in slope when `ParcelPlanningFacts.max_slope_pct` is absent.
- All lookups are performed via `select_related` inside `_resolve_parcel` to minimize query count (`MasterParcel` ⇒ `parcelplanningfacts`, `geometry`).
- `Parcel` table now powers the autocomplete endpoint so address/parcel lookups stay fast without touching slower joined tables.

### Critical Tests To Add
1. **Development form classifier** – unit tests covering representative zoning scenarios (commercial, duplex-allowed, resource, unknown) to confirm the heuristics map parcels into the correct enum and confidence tier.
2. **Constraint extraction** – tests ensuring each GIS flag produces the correct severity + label and omits inactive constraints.
3. **LLM fallback behavior** – integration test or stub verifying that missing credentials surface deterministic fallback text and that the context still renders.
4. **Planning view search flow** – request test that hitting `/planning/?q=P12345` resolves the parcel, attaches the orientation payload, and renders the template without errors even if the parcel lacks `ParcelPlanningFacts`.

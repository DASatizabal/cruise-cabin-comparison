# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cabin Selector is a single-page app for analyzing and selecting cruise cabin options for a Norwegian Cruise Line sailing (Norwegian Joy, Nov 20-23, 2026, 3-night Bahamas). All code lives in `index.html`.

## Data Structure

The active pricing file is `cabin_base_price_20260602.csv` (loaded in `index.html`; the older `cabin_base_price_20260130.csv` is kept for reference). Columns:
- **Cabin Type**: Room category (Inside, Oceanview, Balcony, Club Balcony Suite, Suite, The Haven)
- **Cabin Category**: Specific cabin name/description
- **Cabin Base Price**: Total base price for 2 guests (solo cabins = 1 guest)
- **Up To Guests**: Maximum occupancy (1-8)
- **Sq Ft Total**: Cabin square footage (may be ranges like "214 - 367")
- **Balcony Size**: Balcony square footage ("N/A" for no balcony)
- **Per Person**: Advertised per-person price (base ÷ 4 / quad occupancy); the literal value `(sold out)` marks a cabin as unavailable — the parser sets `cabin.soldOut`, and the UI shows a "Sold Out" banner and disables Compare

## Pricing Logic

- **3-night cruise** (CRUISE_NIGHTS = 3)
- **Base fare**: CSV `basePrice` covers 2 guests; each additional guest beyond 2 adds $438
- **Solo cabins** (maxGuests=1): basePrice covers 1 guest only
- **Tax**: $150/person (not in CSV, hardcoded)
- **Tips**: $20/person/day for Club Balcony Suite & below; $25/person/day for Suite & The Haven. Children under 3 exempt.
- **Drink Package** (toggleable): $85.50 for adults 21+; $37.50 soda/juice substitute for under-21 in guest positions 1-2; $0 for under-21 in positions 3+
- **Dinner Package** (toggleable): $20 for first 2 guests aged 13+; free for children under 13 in positions 1-2; not available for guests 3+
- **Deposit**: Suite/The Haven = 10% of base fare; all others = $100 flat

## Guest System

- Adults (21+) and Children (0-20) with stepper controls
- Children ages entered via popup modal, affecting drink/tip/dinner eligibility
- Adults fill guest positions first, then children sorted by age descending
- Total guests capped at 8 (global) and per-cabin maxGuests

## Architecture

Single `index.html` file containing:
- CSS styles (in `<style>`)
- HTML structure (hero, controls, cabin grid, comparison tray/modal, child age modal, footer)
- JavaScript modules: CSVParser, PriceCalculator, AppState, Renderer, App controller

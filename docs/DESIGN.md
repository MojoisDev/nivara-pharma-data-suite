# Nivara — pharma operations desk

The portfolio's audience is a hiring manager assessing analytical correctness and practical automation.
The dashboard should feel like a calm daily distribution briefing, with the medicine expiry queue
visible as an operational responsibility, not decorative charting.

## Design direction

Warm paper `#f5f4ee`, forest teal `#255f50`, sage `#8ca68d`, and amber for expiry attention. Local Georgia
headlines contrast with small monospace provenance labels and compact native Streamlit controls.
A quiet sidebar anchors reporting scope; a broad revenue rhythm chart is balanced by regional
contribution. Product ranking and therapy mix sit below. Inventory has its own review ledger with
explicit days to expiry and cost-value language. Tabs carry numbered sections; thin rules and ample
spacing replace stacks of generic rounded cards. Charts use the same ink and grid palette.

Native widgets retain keyboard navigation and labels. Risk status uses text as well as color.
Mobile stacks columns through Streamlit's layout; the large heading reduces below 700px.

## Reference research status

The installed Mobbin connector was called with a request for an analytics dashboard containing
revenue trends, date filters and a compact performance table. It returned:

> Mobbin MCP requires a paid plan. Upgrade at https://mobbin.com/pricing to continue.

No reference screens were accessible and no paid upgrade was performed. This interface is an original
implementation, not a reconstruction or a claim of Mobbin-derived research. The integration limitation
is disclosed in the project verification report.

## Screenshot checklist

1. Open the app at `http://localhost:8501`; use all regions/categories and calendar 2025.
2. Capture the header, KPIs, trend and regional chart as `docs/screenshots/sales-desk.png`.
3. Capture therapy mix and top products as `docs/screenshots/product-performance.png`.
4. Open Inventory watch, keep 90 days, capture the attention ledger as `docs/screenshots/inventory-watch.png`.
5. Capture a North-only filtered view and a mobile-width view if including them in a portfolio.
6. Keep the synthetic label and reporting date visible. Do not replace data with real patient/customer data.

Screenshots should represent the running app, not a generated mockup. Screenshots from this session,
if available, are described in `docs/VERIFICATION.md`.

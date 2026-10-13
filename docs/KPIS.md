# KPI contract

All values are synthetic. Dates are calendar dates in the simulated Indian distribution operation;
no timezone conversion is necessary. Reporting window includes both endpoints. INR is the only currency.
A sale unit means one wholesale sale pack (tablet pack, capsule pack or vial), not a patient dose.

| KPI | Definition | Grain / assumptions |
| --- | --- | --- |
| Net revenue | Σ line quantity × actual unit selling price | Sale line; ex-GST, discounts already in price. No returns, credit notes or freight. |
| Monthly revenue | Net revenue grouped by calendar month | Partial months respect the selected date bounds; dashboard fills absent months with zero. SQL returns observed months. |
| Regional revenue | Net revenue by fulfilling warehouse region | Distributor region matches warehouse region in the generated model. |
| Category revenue | Net revenue by batch medicine category | One batch has one medicine; one medicine has one category. |
| Top products | Products grouped by unique SKU, ordered by sale units descending | Whole selected window, top 10 on screen; export contains all matching products. |
| Invoice count | Distinct sale IDs with matching lines | Category filter counts an invoice once even if it has multiple matching lines. |
| Closing units | Received units through end date − all units sold through end date | Batch grain. Includes opening receipts and historical sales outside the reporting start date. |
| Closing value | Σ closing batch units × acquisition cost | Batch cost, not list price. Expired stock remains in book value pending disposal. |
| Near expiry | Held units whose expiry is between end date and end date + horizon | Inclusive boundaries. Expiry on end date is near expiry, not expired. |
| Expired units | Held units whose expiry is before end date | Generator never sells after expiry. No write-off movement is modeled. |
| Stock-at-risk value | Σ held batch units × cost for expiry ≤ end date + horizon | Includes expired + near expiry. Only positive held stock. Default horizon 90 days. |
| COGS | Σ period line quantity × batch cost | Acquisition cost; no operating expenses or tax. |
| Daily average inventory | Mean of each calendar day's closing inventory value during window | Exact weighted event integration; no approximation by beginning/ending balances. |
| Inventory turnover | Period COGS / daily average inventory at cost | Period ratio, not annualized. Zero denominator is NULL / dashboard dash. |

## Reconstructing stock and average inventory

For batch *b*, stock at date *d* is its receipt quantity (only if received by *d*) minus sales
of that batch on or before *d*. Because a batch is received once and may only sell after receipt,
nonnegative total remaining units plus temporal validation implies nonnegative historical stock.

For an inclusive window `[a,z]` of `D = (z-a)+1` days, the exact average is:

```
[Σ received_qty × batch_cost × (z − max(received_date,a) + 1)
 − Σ sold_qty × batch_cost × (z − max(sale_date,a) + 1)] / D
```

Include only receipts and sales on/before *z*. An opening receipt contributes all D days; an opening
sale subtracts all D days. An event on the end date contributes one day. Both numerator and denominator
use the same region/category population. In the hand fixture, 100 packs cost ₹2 each, and 10 sell for
₹15 each on January 6. January 1–10 revenue is ₹150, COGS ₹20, closing stock ₹180, average inventory
`(5×₹200 + 5×₹180)/10 = ₹190`, turnover `20/190 = 0.105263…`.

## Avoiding double-counting

Sales facts join sale line → invoice → batch → medicine → category, with warehouse joined once.
There is one resulting row per line. Batch facts remain one row per batch; historical sale units are
aggregated to batch *before* joining or mapping them. Never sum receipt or closing inventory values
from a line-level join: that repeats each batch once for every sale line.

Money is stored as PostgreSQL `NUMERIC(12,2)`. Python reporting converts prices to integer paise
before multiplying/summing and returns Decimal for monetary KPI totals. Plotly and CSV chart data use
rupees as display floats; the daily average and turnover use floating point only after exact sums.

## Scope of filters

Start/end dates filter sale performance. Closing inventory uses end date only, including earlier
movements. Regional filters use the warehouse region; category filters use batch medicine category.
Dashboard selections can be empty, yielding an empty report. SQL parameters use NULL for all regions
or categories and accept one region/category per query. End date cannot exceed the loaded snapshot
in the Python reporting layer. Raw SQL callers must enforce the same date-window contract.

## Simulation limits

Fixed seed 20251011. Calendar period January 2024–December 2025; four receipt waves per medicine per
warehouse. More invoices occur later in the period; regions have different demand weights. Medicines
and customers have fictional SYN-prefixed names. FEFO allocates from the earliest eligible expiry
first and can split a requested quantity across two batches. Receipts are independent batch lots.

No patients, real brands, cold-chain monitoring, inter-warehouse transfers, returns, credit notes,
stock adjustments, disposal, GST compliance or clinical recommendations are modeled by the generator.
Phases 2 and 3 add validation and automation around this unchanged KPI contract.
Expired stock is deliberately retained so the review ledger has explicit book-value risk to explain.

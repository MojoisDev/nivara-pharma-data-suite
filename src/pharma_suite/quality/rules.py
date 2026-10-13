"""Stable rule catalog: change version when a rule's meaning changes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    dimension: str
    severity: str
    description: str
    remediation: str
    version: str = "1.0"


CATALOG = {
    "CMP001": Rule(
        "completeness",
        "error",
        "Required field is missing or blank",
        "Confirm the value with the synthetic source; supply an explicit audited correction.",
    ),
    "CMP002": Rule(
        "completeness",
        "critical",
        "Required entity has no records",
        "Restore the complete feed; partial snapshots cannot be approved.",
    ),
    "UNI001": Rule(
        "uniqueness",
        "critical",
        "Duplicate primary identifier",
        "Review both copies; explicitly tombstone the erroneous row or correct its ID.",
    ),
    "UNI002": Rule(
        "uniqueness",
        "error",
        "Duplicate business reference",
        "Review the business reference; no automatic renumbering.",
    ),
    "UNI003": Rule(
        "uniqueness",
        "error",
        "Batch number violates the production global namespace",
        "Use an explicitly reviewed global batch reference compatible with Phase 1.",
    ),
    "VAL001": Rule(
        "validity",
        "error",
        "Date must be a real ISO YYYY-MM-DD date",
        "Confirm and explicitly correct the date; never infer a manufacturing or expiry date.",
    ),
    "VAL002": Rule(
        "validity",
        "critical",
        "Quantity must be an integer in the permitted range",
        "Reconcile units against the source; negative closing inventory is not permitted.",
    ),
    "VAL003": Rule(
        "validity",
        "error",
        "Price must be finite, positive, within bounds and at most two decimal places",
        "Review the source currency and amount; do not automatically change prices.",
    ),
    "VAL004": Rule(
        "validity",
        "error",
        "Identifier must be a positive integer",
        "Review the identifier and dependent references manually.",
    ),
    "VAL005": Rule(
        "validity",
        "warning",
        "Contact email format is invalid",
        "Correct the contact from a synthetic source; no external email is sent.",
    ),
    "VAL006": Rule(
        "validity",
        "error",
        "Batch reference format is invalid",
        "Review the lot reference; expected 3–30 uppercase alphanumeric/hyphen characters.",
    ),
    "VAL007": Rule(
        "validity",
        "error",
        "Region is outside the configured Indian region set",
        "Use North, South, East or West after source review.",
    ),
    "VAL008": Rule(
        "validity",
        "error",
        "Sellability must be a boolean",
        "Explicitly review availability; unknown is not treated as sellable.",
    ),
    "VAL009": Rule(
        "validity",
        "warning",
        "Selling price exceeds the configured list-price ceiling",
        "Review contract pricing; discounts are allowed and differing prices alone are not errors.",
    ),
    "REF001": Rule(
        "referential_integrity",
        "critical",
        "Referenced entity does not exist in staging",
        "Restore the parent or explicitly correct the reference before approved load.",
    ),
    "CON001": Rule(
        "consistency",
        "critical",
        "Expiry must be strictly after manufacturing",
        "Review original dates; never infer a new expiry.",
    ),
    "CON002": Rule(
        "consistency",
        "error",
        "Receipt date is incompatible with manufacturing or expiry",
        "Review receipt and batch dates against the source.",
    ),
    "CON003": Rule(
        "consistency",
        "critical",
        "Sale predates manufacturing",
        "Review the sale and batch association and source dates.",
    ),
    "CON004": Rule(
        "consistency",
        "critical",
        "Sale predates the batch receipt",
        "Reconcile the chronological movement history.",
    ),
    "CON005": Rule(
        "consistency",
        "critical",
        "Sale occurs after batch expiry",
        "Quarantine the sale for explicit review; expiry-day sales are allowed by this model.",
    ),
    "CON006": Rule(
        "consistency",
        "critical",
        "Sale line, invoice and batch warehouses disagree",
        "Review the allocation; transfers are not modeled.",
    ),
    "CON007": Rule(
        "consistency",
        "critical",
        "Declared medicine does not match the batch medicine",
        "Review both identifiers; never substitute an ID automatically.",
    ),
    "CON008": Rule(
        "consistency",
        "error",
        "Declared line total differs from quantity times unit price",
        "Reconcile the declared amount with the synthetic source.",
    ),
    "CON009": Rule(
        "consistency",
        "error",
        "Invoice total differs from calculated line totals",
        "Review all invoice lines, discounts and source totals.",
    ),
    "CON010": Rule(
        "consistency",
        "critical",
        "Expired stock is marked sellable",
        "Explicitly mark expired stock unavailable; expired held inventory is legitimate.",
    ),
    "CON011": Rule(
        "consistency",
        "critical",
        "Closing inventory contradicts receipts and sales",
        "Reconcile movements; no silent stock balancing adjustment.",
    ),
    "CON012": Rule(
        "consistency",
        "critical",
        "Chronological sales exceed batch receipt units",
        "Review oversold lines against available stock and receipt dates.",
    ),
    "CON013": Rule(
        "consistency",
        "error",
        "Transaction or inventory snapshot is incompatible with the declared snapshot",
        "Review the feed cutoff and snapshot date; do not silently move dates.",
    ),
    "CON014": Rule(
        "consistency",
        "error",
        "Distributor and warehouse regions differ",
        "Review distributor assignment; cross-region fulfillment is not modeled in Phase 1.",
    ),
    "CON015": Rule(
        "consistency",
        "error",
        "Invoice has no sale lines",
        "Restore the missing lines or explicitly reject the invoice.",
    ),
    "CON016": Rule(
        "consistency",
        "error",
        "Batch lacks its inventory snapshot",
        "Restore its closing position; partial snapshots cannot be approved.",
    ),
    "TIM001": Rule(
        "timeliness",
        "warning",
        "Import timestamp is missing, malformed, future-dated or older than threshold",
        "Review the feed delivery timestamp; replay uses an explicit historical clock.",
    ),
    "TIM002": Rule(
        "timeliness",
        "warning",
        "Reporting feed date is missing, invalid, future-dated or delayed",
        "Review the last reported business date and feed lag.",
    ),
}

REQUIRED = {
    "categories": ("id", "name"),
    "medicines": ("id", "category_id", "name", "sku", "dosage_form", "list_price", "manufacturer"),
    "distributors": ("id", "name", "region", "city"),
    "warehouses": ("id", "name", "region", "city"),
    "batches": (
        "id",
        "medicine_id",
        "warehouse_id",
        "batch_number",
        "manufacture_date",
        "received_date",
        "expiry_date",
        "unit_cost",
        "received_quantity",
    ),
    "inventory": ("batch_id", "quantity", "snapshot_date", "is_sellable"),
    "sales": (
        "id",
        "distributor_id",
        "warehouse_id",
        "sale_date",
        "invoice_number",
        "invoice_total",
    ),
    "sales_items": (
        "id",
        "sale_id",
        "warehouse_id",
        "batch_id",
        "quantity",
        "unit_price",
        "medicine_id",
        "line_total",
    ),
}
FOREIGN_KEYS = {
    "medicines": {"category_id": "categories"},
    "batches": {"medicine_id": "medicines", "warehouse_id": "warehouses"},
    "inventory": {"batch_id": "batches"},
    "sales": {"distributor_id": "distributors", "warehouse_id": "warehouses"},
    "sales_items": {
        "sale_id": "sales",
        "warehouse_id": "warehouses",
        "batch_id": "batches",
        "medicine_id": "medicines",
    },
}
BUSINESS_KEYS = {
    "categories": ("name",),
    "medicines": ("sku",),
    "distributors": ("name",),
    "warehouses": ("name",),
    "batches": ("warehouse_id", "batch_number"),
    "sales": ("invoice_number",),
    "sales_items": ("sale_id", "batch_id"),
}

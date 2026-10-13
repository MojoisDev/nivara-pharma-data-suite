-- Exact daily end-of-day average inventory at cost; period ratio, not annualised.
WITH selected_batches AS (
 SELECT b.* FROM batches b JOIN medicines m ON m.id=b.medicine_id
 JOIN categories c ON c.id=m.category_id JOIN warehouses w ON w.id=b.warehouse_id
 WHERE b.received_date <= CAST(:end_date AS date)
 AND (CAST(:region AS text) IS NULL OR w.region=CAST(:region AS text))
 AND (CAST(:category AS text) IS NULL OR c.name=CAST(:category AS text))
), receipt_days AS (
 SELECT COALESCE(SUM(received_quantity*unit_cost*
   (CAST(:end_date AS date)-GREATEST(received_date,CAST(:start_date AS date))+1)),0) AS value
 FROM selected_batches
), sale_days AS (
 SELECT COALESCE(SUM(si.quantity*b.unit_cost*
   (CAST(:end_date AS date)-GREATEST(s.sale_date,CAST(:start_date AS date))+1)),0) AS value,
 COALESCE(SUM(CASE WHEN s.sale_date>=CAST(:start_date AS date) THEN si.quantity*b.unit_cost ELSE 0 END),0) AS cogs
 FROM sales_items si JOIN sales s ON s.id=si.sale_id
 JOIN selected_batches b ON b.id=si.batch_id WHERE s.sale_date<=CAST(:end_date AS date)
), average AS (
 SELECT (r.value-s.value)/(CAST(:end_date AS date)-CAST(:start_date AS date)+1) AS average_inventory, s.cogs
 FROM receipt_days r CROSS JOIN sale_days s
)
SELECT average_inventory, cogs, cogs/NULLIF(average_inventory,0) AS turnover FROM average;

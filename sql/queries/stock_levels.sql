WITH sold AS (
 SELECT si.batch_id, SUM(si.quantity) AS units FROM sales_items si
 JOIN sales s ON s.id=si.sale_id WHERE s.sale_date <= CAST(:end_date AS date)
 GROUP BY si.batch_id
), stock AS (
 SELECT b.id AS batch_id, b.batch_number, m.name AS medicine, c.name AS category,
        w.region, w.name AS warehouse, b.expiry_date, b.unit_cost,
        b.received_quantity - COALESCE(sold.units,0) AS stock_units
 FROM batches b LEFT JOIN sold ON sold.batch_id=b.id
 JOIN medicines m ON m.id=b.medicine_id JOIN categories c ON c.id=m.category_id
 JOIN warehouses w ON w.id=b.warehouse_id
 WHERE b.received_date <= CAST(:end_date AS date)
   AND (CAST(:region AS text) IS NULL OR w.region=CAST(:region AS text))
   AND (CAST(:category AS text) IS NULL OR c.name=CAST(:category AS text))
)
SELECT *, stock_units*unit_cost AS stock_value FROM stock ORDER BY batch_id;

-- SQLAlchemy named bind parameters; synthetic-only reporting.
WITH sale_lines AS (
 SELECT s.id AS sale_id, s.sale_date, si.quantity, si.unit_price, b.unit_cost,
        m.name AS medicine, c.name AS category, w.region
 FROM sales_items si JOIN sales s ON s.id=si.sale_id
 JOIN batches b ON b.id=si.batch_id JOIN medicines m ON m.id=b.medicine_id
 JOIN categories c ON c.id=m.category_id JOIN warehouses w ON w.id=s.warehouse_id
 WHERE s.sale_date BETWEEN CAST(:start_date AS date) AND CAST(:end_date AS date)
   AND (CAST(:region AS text) IS NULL OR w.region=CAST(:region AS text))
   AND (CAST(:category AS text) IS NULL OR c.name=CAST(:category AS text))
)
SELECT region, SUM(quantity*unit_price) AS revenue FROM sale_lines GROUP BY region ORDER BY revenue DESC;

-- Synthetic seed data (fabricated). 150 sales rows over 30 days.
INSERT INTO sales (sale_date, product, region, quantity, amount, customer_id)
SELECT
    DATE '2026-09-01' + (g % 30),
    (ARRAY['Widget', 'Gadget', 'Gizmo', 'Doohickey'])[1 + (g % 4)],
    (ARRAY['North', 'South', 'East', 'West'])[1 + (g % 3)],
    1 + (g % 7),
    ROUND(((g * 37) % 500 + 20)::numeric, 2),
    1 + (g % 25)
FROM generate_series(1, 150) AS g;

INSERT INTO customers_private (customer_id, full_name, email, national_id)
SELECT i, 'Synthetic Customer ' || i, 'synthetic' || i || '@example.invalid', 'FAKE-' || LPAD(i::text, 6, '0')
FROM generate_series(1, 25) AS i;

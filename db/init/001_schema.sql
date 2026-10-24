-- Synthetic demo schema. All data is fabricated.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO actiongate_reader;

CREATE TABLE sales (
    id          SERIAL PRIMARY KEY,
    sale_date   DATE NOT NULL,
    product     TEXT NOT NULL,
    region      TEXT NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    amount      NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    customer_id INTEGER NOT NULL
);

CREATE TABLE customers_private (
    customer_id INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    national_id TEXT NOT NULL
);

-- The only relation the agent's role may read. The view runs with the owner's
-- privileges, so the reader does not need direct access to the base table.
CREATE VIEW sales_summary_safe AS
    SELECT sale_date, product, region, quantity, amount
    FROM sales;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM actiongate_reader;
GRANT SELECT ON sales_summary_safe TO actiongate_reader;

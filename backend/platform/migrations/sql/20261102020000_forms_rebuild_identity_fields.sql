-- `forms` gets rebuilt from scratch around the real field set the new
-- flow needs (identity, birth, document, contact, financial), instead of
-- the old one-shot KYC+financial form. `document_type`/`document_number`
-- keep their meaning and stay as they were; everything else from the old
-- shape is dropped outright -- `full_name` in particular stops making
-- sense once name is split into parts.
--
-- All new columns are nullable even where a field is "required" from the
-- business side (name, last_name, email) -- that rule is enforced by the
-- Lambda's input validation, not the schema. `update_user_form` only
-- writes name/second_name/last_name/second_last_name/document_type/
-- document_number/email today; the rest wait for the handlers that will
-- collect them.
--
-- Paired changes: libs/orm/forms.py, services/forms/src/handlers/
-- update_user_form (new, the only writer today), services/forms/src/
-- handlers/upsert_mine (removed, fully superseded).

-- +migrate up

ALTER TABLE forms ADD COLUMN name VARCHAR(100);
ALTER TABLE forms ADD COLUMN second_name VARCHAR(100);
ALTER TABLE forms ADD COLUMN last_name VARCHAR(100);
ALTER TABLE forms ADD COLUMN second_last_name VARCHAR(100);
ALTER TABLE forms ADD COLUMN gender VARCHAR(20);
ALTER TABLE forms ADD COLUMN birth_country VARCHAR(100);
ALTER TABLE forms ADD COLUMN birth_department VARCHAR(100);
ALTER TABLE forms ADD COLUMN birth_city VARCHAR(100);
ALTER TABLE forms ADD COLUMN nationality VARCHAR(100);
ALTER TABLE forms ADD COLUMN email VARCHAR(200);
ALTER TABLE forms ADD COLUMN document_issuance_date TIMESTAMPTZ;
ALTER TABLE forms ADD COLUMN document_issuance_country VARCHAR(100);
ALTER TABLE forms ADD COLUMN document_issuance_department VARCHAR(100);
ALTER TABLE forms ADD COLUMN document_issuance_city VARCHAR(100);
ALTER TABLE forms ADD COLUMN phone_ext VARCHAR(10);
ALTER TABLE forms ADD COLUMN phone_number VARCHAR(20);
ALTER TABLE forms ADD COLUMN civil_status VARCHAR(20);
ALTER TABLE forms ADD COLUMN education_level VARCHAR(100);
ALTER TABLE forms ADD COLUMN is_pep BOOLEAN;
ALTER TABLE forms ADD COLUMN is_tax_declarant BOOLEAN;

-- birth_date was DATE and monthly_income/monthly_expenses/total_assets/
-- total_liabilities were NUMERIC(15,2) in the old shape; dropped below
-- and re-added to match the new columns' types (TIMESTAMPTZ, DOUBLE
-- PRECISION).
ALTER TABLE forms DROP COLUMN birth_date;
ALTER TABLE forms ADD COLUMN birth_date TIMESTAMPTZ;
ALTER TABLE forms DROP COLUMN monthly_income;
ALTER TABLE forms ADD COLUMN monthly_income DOUBLE PRECISION;
ALTER TABLE forms DROP COLUMN monthly_expenses;
ALTER TABLE forms ADD COLUMN monthly_expenses DOUBLE PRECISION;
ALTER TABLE forms DROP COLUMN total_assets;
ALTER TABLE forms ADD COLUMN total_assets DOUBLE PRECISION;
ALTER TABLE forms DROP COLUMN total_liabilities;
ALTER TABLE forms ADD COLUMN total_liabilities DOUBLE PRECISION;

ALTER TABLE forms DROP COLUMN full_name;
ALTER TABLE forms DROP COLUMN phone;
ALTER TABLE forms DROP COLUMN address;
ALTER TABLE forms DROP COLUMN city;
ALTER TABLE forms DROP COLUMN occupation;
ALTER TABLE forms DROP COLUMN economic_activity;
ALTER TABLE forms DROP COLUMN source_of_funds;
ALTER TABLE forms DROP COLUMN is_peps;

-- +migrate down

-- Best-effort: the dropped columns come back nullable, not NOT NULL like
-- they started -- restoring NOT NULL would fail outright on any row
-- written by `update_user_form`, which never sets them.
ALTER TABLE forms ADD COLUMN full_name VARCHAR(200);
ALTER TABLE forms ADD COLUMN phone VARCHAR(30);
ALTER TABLE forms ADD COLUMN address VARCHAR(300);
ALTER TABLE forms ADD COLUMN city VARCHAR(120);
ALTER TABLE forms ADD COLUMN occupation VARCHAR(120);
ALTER TABLE forms ADD COLUMN economic_activity VARCHAR(120);
ALTER TABLE forms ADD COLUMN source_of_funds VARCHAR(200);
ALTER TABLE forms ADD COLUMN is_peps BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE forms DROP COLUMN birth_date;
ALTER TABLE forms ADD COLUMN birth_date DATE;
ALTER TABLE forms DROP COLUMN monthly_income;
ALTER TABLE forms ADD COLUMN monthly_income NUMERIC(15, 2);
ALTER TABLE forms DROP COLUMN monthly_expenses;
ALTER TABLE forms ADD COLUMN monthly_expenses NUMERIC(15, 2);
ALTER TABLE forms DROP COLUMN total_assets;
ALTER TABLE forms ADD COLUMN total_assets NUMERIC(15, 2);
ALTER TABLE forms DROP COLUMN total_liabilities;
ALTER TABLE forms ADD COLUMN total_liabilities NUMERIC(15, 2);

ALTER TABLE forms DROP COLUMN name;
ALTER TABLE forms DROP COLUMN second_name;
ALTER TABLE forms DROP COLUMN last_name;
ALTER TABLE forms DROP COLUMN second_last_name;
ALTER TABLE forms DROP COLUMN gender;
ALTER TABLE forms DROP COLUMN birth_country;
ALTER TABLE forms DROP COLUMN birth_department;
ALTER TABLE forms DROP COLUMN birth_city;
ALTER TABLE forms DROP COLUMN nationality;
ALTER TABLE forms DROP COLUMN email;
ALTER TABLE forms DROP COLUMN document_issuance_date;
ALTER TABLE forms DROP COLUMN document_issuance_country;
ALTER TABLE forms DROP COLUMN document_issuance_department;
ALTER TABLE forms DROP COLUMN document_issuance_city;
ALTER TABLE forms DROP COLUMN phone_ext;
ALTER TABLE forms DROP COLUMN phone_number;
ALTER TABLE forms DROP COLUMN civil_status;
ALTER TABLE forms DROP COLUMN education_level;
ALTER TABLE forms DROP COLUMN is_pep;
ALTER TABLE forms DROP COLUMN is_tax_declarant;

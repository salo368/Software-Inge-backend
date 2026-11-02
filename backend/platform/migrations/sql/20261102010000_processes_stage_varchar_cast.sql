-- Lets a varchar be assigned to processes.stage without an explicit cast.
-- The ORM maps the column as a plain String, so pg8000 binds `%s::VARCHAR`,
-- and Postgres has no assignment cast from varchar to an enum by default.
-- WITH INOUT goes through the enum's input function, so labels outside
-- process_stage are still rejected by the database.

-- +migrate up

CREATE CAST (character varying AS process_stage) WITH INOUT AS ASSIGNMENT;

-- +migrate down

DROP CAST IF EXISTS (character varying AS process_stage);

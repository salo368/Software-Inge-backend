-- Bridges `processes` to the new signatures service: once a process has
-- all required files, `get_required_files` invokes `generate_sign`
-- (populates the bank's investment order and opens a signature ceremony
-- for it), which stores the resulting `signature_id` here so the front
-- end knows where to redirect for the signing flow.
--
-- Paired changes: libs/orm/processes.py, services/processes/src/workers/
-- generate_sign, services/processes/src/handlers/get_required_files,
-- services/processes/src/handlers/get_processes.

-- +migrate up

ALTER TABLE processes ADD COLUMN signature_id UUID;

-- +migrate down

ALTER TABLE processes DROP COLUMN signature_id;

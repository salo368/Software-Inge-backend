-- `form_snapshot` is renamed to `submitted_form`: it holds the user's
-- form (fetched from forms.get_form) as it stood at the moment
-- `set_process_form` moved the process into the 'DOCUMENTS' stage.

-- +migrate up

ALTER TABLE processes RENAME COLUMN form_snapshot TO submitted_form;

-- +migrate down

ALTER TABLE processes RENAME COLUMN submitted_form TO form_snapshot;

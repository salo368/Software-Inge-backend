-- The three biometric evidence slots for the BIOMETRICS stage. Each is
-- set by `set_biometrics` only after Rekognition validates the upload
-- (see libs/utils/biometrics.py); nullable because they fill in one at
-- a time, and the key layout matches `upload_biometrics`:
--   signatures/{signature_id}/{id_front|id_back|face}.{jpg|png}
--
-- Paired changes: libs/orm/signatures.py, libs/utils/biometrics.py (new),
-- services/signatures/src/handlers/{upload_biometrics,set_biometrics,
-- get_required_biometrics} (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN id_front_s3_key VARCHAR(300);
ALTER TABLE signatures ADD COLUMN id_back_s3_key VARCHAR(300);
ALTER TABLE signatures ADD COLUMN id_face_s3_key VARCHAR(300);

-- +migrate down

ALTER TABLE signatures DROP COLUMN id_front_s3_key;
ALTER TABLE signatures DROP COLUMN id_back_s3_key;
ALTER TABLE signatures DROP COLUMN id_face_s3_key;

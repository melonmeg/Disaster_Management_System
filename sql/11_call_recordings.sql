-- =====================================================================
-- 11_call_recordings.sql   (one-time migration, additive only)
-- Stores the audio recording of an emergency call in the calls table.
--
--   calls.transcript        LONGTEXT  = CLOB (already existed): short text typed by the dispatcher
--   calls.audio_recording   LONGBLOB  = BLOB (new): the recorded audio itself
--
-- The transcription of the audio (full text, timestamped segments, language, engine used) is stored
-- in MongoDB (collection call_transcripts, keyed by call_id), not here.
-- Existing rows keep NULL in all new columns. The API limits uploads (MAX_RECORDING_MB, default 25) and
-- never selects audio_recording except on the dedicated download endpoint.
-- =====================================================================

ALTER TABLE calls
    ADD COLUMN audio_recording   LONGBLOB      NULL,
    ADD COLUMN audio_mime_type   VARCHAR(50)   NULL,
    ADD COLUMN audio_filename    VARCHAR(255)  NULL,
    ADD COLUMN audio_size_bytes  INT UNSIGNED  NULL,
    ADD COLUMN audio_sha256      CHAR(64)      NULL,      -- integrity check + links a transcript to the exact audio
    ADD COLUMN audio_uploaded_at DATETIME      NULL,
    ADD CONSTRAINT chk_calls_audio_meta CHECK (
        (audio_recording IS NULL AND audio_mime_type IS NULL AND audio_size_bytes IS NULL AND audio_sha256 IS NULL)
        OR (audio_recording IS NOT NULL AND audio_mime_type IS NOT NULL AND audio_size_bytes > 0
            AND audio_sha256 IS NOT NULL));

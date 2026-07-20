-- ============================================================
--  Migration: cached resume text for per-position matching
--  Run this ONLY if your drdo_portal database already existed
--  before the per-position applicant ranking feature was added
--  (i.e. schema.sql was applied previously without this column).
--
--  Usage: mysql -u root -p drdo_portal < migrate_position_match.sql
--
--  Safe to re-run: MySQL will error with "Duplicate column name"
--  (1060) on columns that already exist - that's expected, ignore it.
-- ============================================================

USE drdo_portal;

ALTER TABLE candidate_profiles ADD COLUMN resume_text TEXT;

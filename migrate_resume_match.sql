-- ============================================================
--  Migration: resume upload + AI job-role match columns
--  Run this ONLY if your drdo_portal database already existed
--  before the resume-matching feature was added (i.e. schema.sql
--  was applied previously without these columns).
--
--  Usage: mysql -u root -p drdo_portal < migrate_resume_match.sql
--
--  Safe to re-run: MySQL will error with "Duplicate column name"
--  (1060) on columns that already exist - that's expected, ignore it.
-- ============================================================

USE drdo_portal;

ALTER TABLE candidate_profiles ADD COLUMN resume_best_role  VARCHAR(100);
ALTER TABLE candidate_profiles ADD COLUMN resume_best_pct   DECIMAL(5,2);
ALTER TABLE candidate_profiles ADD COLUMN resume_match_json TEXT;
ALTER TABLE candidate_profiles ADD COLUMN resume_matched_at DATETIME;

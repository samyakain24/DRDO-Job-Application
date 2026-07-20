-- ============================================================
--  DRDO Internship Portal - MySQL Database Schema
--  Run this file first: mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS drdo_portal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE drdo_portal;

-- ============================================================
-- 1. USERS  (admin / hr / candidate)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(150)  NOT NULL,
    email         VARCHAR(150)  NOT NULL UNIQUE,
    password_hash VARCHAR(255)  NOT NULL,
    role          ENUM('admin','hr','candidate') NOT NULL DEFAULT 'candidate',
    phone         VARCHAR(20),
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. CANDIDATE PROFILES
-- ============================================================
CREATE TABLE IF NOT EXISTS candidate_profiles (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT          NOT NULL UNIQUE,
    dob             DATE,
    gender          ENUM('Male','Female','Other'),
    address         TEXT,
    college         VARCHAR(200),
    degree          VARCHAR(100),
    branch          VARCHAR(100),
    graduation_year YEAR,
    cgpa            DECIMAL(4,2),
    skills          TEXT,
    resume_url      VARCHAR(300),
    -- Resume ↔ job-role match results, produced by resume_matcher/match.py
    -- whenever the candidate (re)uploads a resume on their profile page.
    resume_best_role  VARCHAR(100),        -- e.g. "AIML jobs"
    resume_best_pct   DECIMAL(5,2),        -- classifier confidence for that role, 0-100
    resume_match_json TEXT,                -- full per-role breakdown (JSON array)
    resume_matched_at DATETIME,
    -- Cached plain-text extraction of the resume PDF, used to score the
    -- candidate against a specific internship position's own description/
    -- requirements text on demand (see resume_matcher/match.py::score_resume_against_text).
    resume_text     TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ============================================================
-- 3. INTERNSHIP POSITIONS  (created by HR)
-- ============================================================
CREATE TABLE IF NOT EXISTS internship_positions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    title         VARCHAR(200)  NOT NULL,
    department    VARCHAR(150)  NOT NULL,
    location      VARCHAR(100)  DEFAULT 'DRDO HQ, New Delhi',
    description   TEXT,
    requirements  TEXT,
    duration      VARCHAR(50),          -- e.g. "2 months"
    stipend       DECIMAL(10,2),
    total_seats   INT           NOT NULL DEFAULT 1,
    deadline      DATE,
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_by    INT          NOT NULL, -- FK to users (hr)
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- ============================================================
-- 4. APPLICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS applications (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    INT          NOT NULL,
    position_id     INT          NOT NULL,
    cover_letter    TEXT,
    status          ENUM('Submitted','Under Review','Shortlisted','Interview Scheduled','Selected','Rejected')
                    NOT NULL DEFAULT 'Submitted',
    hr_remarks      TEXT,
    applied_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_candidate_position (candidate_id, position_id),
    FOREIGN KEY (candidate_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (position_id)  REFERENCES internship_positions(id) ON DELETE CASCADE
);

-- ============================================================
-- 5. APPLICATION STATUS HISTORY  (audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS application_history (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    application_id  INT          NOT NULL,
    old_status      VARCHAR(50),
    new_status      VARCHAR(50)  NOT NULL,
    remarks         TEXT,
    changed_by      INT          NOT NULL, -- FK to users
    changed_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by)     REFERENCES users(id)
);

-- ============================================================
-- 6. SEED DATA  (admin + 1 HR + 2 candidates + positions)
-- ============================================================

-- Passwords are hashed via werkzeug pbkdf2:sha256
-- admin@drdo.in      → password: Admin@1234
-- hr@drdo.in         → password: Hr@1234
-- alice@example.com  → password: Alice@1234
-- bob@example.com    → password: Bob@1234
-- (re-generate hashes with: python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('YourPass'))")

INSERT INTO users (full_name, email, password_hash, role, phone) VALUES
('DRDO Admin',    'admin@drdo.in',      'pbkdf2:sha256:600000$drdo$7b2a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b', 'admin', '9000000001'),
('Dr. Ramesh HR', 'hr@drdo.in',         'pbkdf2:sha256:600000$drdo$7b2a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b', 'hr',    '9000000002'),
('Alice Sharma',  'alice@example.com',  'pbkdf2:sha256:600000$drdo$7b2a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b', 'candidate', '9111111111'),
('Bob Verma',     'bob@example.com',    'pbkdf2:sha256:600000$drdo$7b2a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b', 'candidate', '9222222222');

-- Every candidate needs a matching candidate_profiles row (the /register
-- route and setup_demo.py create this automatically; raw seed data doesn't
-- get that for free). Without it, candidate_profile()'s UPDATE ... WHERE
-- user_id=%s silently affects 0 rows - profile edits look like they save
-- but never persist.
INSERT INTO candidate_profiles (user_id)
SELECT id FROM users WHERE email IN ('alice@example.com', 'bob@example.com');

INSERT INTO internship_positions (title, department, location, description, requirements, duration, stipend, total_seats, deadline, is_active, created_by) VALUES
('AI/ML Research Intern',        'Electronics & Radar', 'DRDO, Bangalore',
 'Work on AI-based radar signal processing algorithms.',
 'B.Tech/M.Tech in CS/ECE, Python, TensorFlow/PyTorch', '2 Months', 8000.00, 5, '2026-08-31', 1, 2),

('Embedded Systems Intern',      'Armament Research',   'DRDO, Pune',
 'Design and test embedded firmware for weapon systems.',
 'B.Tech in ECE/EEE, C/C++, ARM Cortex experience preferred', '3 Months', 10000.00, 3, '2026-09-15', 1, 2),

('Data Science Intern',          'Life Sciences',       'DRDO, Delhi',
 'Data analysis and modelling for biomedical research.',
 'B.Tech/B.Sc in CS/Statistics, Python, SQL, pandas, sklearn', '2 Months', 7500.00, 4, '2026-08-01', 1, 2),

('Cybersecurity Research Intern','Information Systems', 'DRDO, Hyderabad',
 'Research in network security and cryptography.',
 'B.Tech in CS/IT, networking fundamentals, ethical hacking basics', '3 Months', 9000.00, 2, '2026-09-30', 1, 2);

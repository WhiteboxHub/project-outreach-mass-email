-- ======================================================================
-- PRODUCTION MIGRATION: Automation Workflow System
-- Run this SQL on your PRODUCTION database
-- Date: 2026-02-17
-- ======================================================================

-- ==========================================
-- 1. Ensure columns exist on candidate_marketing
-- ==========================================
-- NOTE: If columns already exist, these will error (safe to ignore)
-- ALTER TABLE candidate_marketing ADD COLUMN run_daily_workflow TINYINT NOT NULL DEFAULT 0;
-- ALTER TABLE candidate_marketing ADD COLUMN run_weekly_workflow TINYINT NOT NULL DEFAULT 0;


-- ==========================================
-- 2. Drop Old Triggers (if they exist)
-- ==========================================
DROP TRIGGER IF EXISTS trg_prepare_daily_vendor_workflow;
DROP TRIGGER IF EXISTS trg_prepare_weekly_vendor_workflow;


-- ==========================================
-- 3. Create Daily Workflow Trigger
--    When run_daily_workflow is toggled from 0 -> 1,
--    inject candidate credentials into the schedule's run_parameters.
--    After the workflow runs successfully, it will reset this flag to 0.
-- ==========================================
DELIMITER $$

CREATE TRIGGER trg_prepare_daily_vendor_workflow
AFTER UPDATE ON candidate_marketing
FOR EACH ROW
BEGIN
    IF NEW.run_daily_workflow = 1
       AND OLD.run_daily_workflow = 0 THEN

        UPDATE automation_workflows_schedule s
        JOIN automation_workflows w
          ON s.automation_workflow_id = w.id
        SET s.run_parameters = JSON_OBJECT(
            'candidate_id', NEW.candidate_id,
            'email', NEW.email,
            'imap_password', NEW.imap_password,
            'linkedin_username', NEW.linkedin_username,
            'linkedin_passwd', NEW.linkedin_passwd,
            'trigger_type', 'daily',
            'activated_at', NOW()
        )
        WHERE w.workflow_key = 'daily_vendor_outreach'
          AND s.enabled = 1;

    END IF;
END$$

DELIMITER ;


-- ==========================================
-- 4. Create Weekly Workflow Trigger
-- ==========================================
DELIMITER $$

CREATE TRIGGER trg_prepare_weekly_vendor_workflow
AFTER UPDATE ON candidate_marketing
FOR EACH ROW
BEGIN
    IF NEW.run_weekly_workflow = 1
       AND OLD.run_weekly_workflow = 0 THEN

        UPDATE automation_workflows_schedule s
        JOIN automation_workflows w
          ON s.automation_workflow_id = w.id
        SET s.run_parameters = JSON_OBJECT(
            'candidate_id', NEW.candidate_id,
            'email', NEW.email,
            'imap_password', NEW.imap_password,
            'linkedin_username', NEW.linkedin_username,
            'linkedin_passwd', NEW.linkedin_passwd,
            'trigger_type', 'weekly',
            'activated_at', NOW()
        )
        WHERE w.workflow_key = 'weekly_vendor_outreach'
          AND s.enabled = 1;

    END IF;
END$$

DELIMITER ;


-- ==========================================
-- 5. Fix Workflow 1 (Daily Vendor Outreach)
--    - Fix recipient_list_sql to use candidate_marketing + candidate tables
--    - Fix success_reset_sql column name (was daily_outreach_flag, should be run_daily_workflow)
-- ==========================================

UPDATE automation_workflows
SET recipient_list_sql = '
    SELECT
        v.id,
        v.email,
        v.full_name AS contact_name,
        v.company_name,
        v.job_source,
        c.candidate_id,
        c.full_name AS candidate_name,
        CASE
            WHEN c.linkedin_id LIKE ''http%'' THEN c.linkedin_id
            ELSE CONCAT(''https://'', c.linkedin_id)
        END AS linkedin_url
    FROM vendor_contact_extracts v
    CROSS JOIN (
        SELECT cm.id, cm.candidate_id, c.full_name, c.linkedin_id
        FROM candidate_marketing cm
        JOIN candidate c ON c.id = cm.candidate_id
        WHERE cm.status = ''active''
          AND cm.run_daily_workflow = 1
          AND c.linkedin_id LIKE ''%linkedin.com%''
          AND c.full_name IS NOT NULL
        LIMIT 1
    ) c
    ON 1=1
    WHERE DATE(v.created_at) = CURRENT_DATE
',
    parameters_config = '{"success_reset_sql": "UPDATE candidate_marketing SET run_daily_workflow = 0 WHERE candidate_id = :candidate_id"}'
WHERE id = 1;


-- ==========================================
-- 6. Fix Workflow 3 (Weekly Vendor Outreach)
--    - Fix recipient_list_sql (was using non-existent extracted_vendors table)
--    - Fix success_reset_sql column name (was weekly_outreach_flag, should be run_weekly_workflow)
-- ==========================================

UPDATE automation_workflows
SET recipient_list_sql = '
    SELECT
        v.id,
        v.email,
        v.full_name AS contact_name,
        v.company_name,
        v.job_source,
        c.candidate_id,
        c.full_name AS candidate_name,
        CASE
            WHEN c.linkedin_id LIKE ''http%'' THEN c.linkedin_id
            ELSE CONCAT(''https://'', c.linkedin_id)
        END AS linkedin_url
    FROM vendor_contact_extracts v
    CROSS JOIN (
        SELECT cm.id, cm.candidate_id, c.full_name, c.linkedin_id
        FROM candidate_marketing cm
        JOIN candidate c ON c.id = cm.candidate_id
        WHERE cm.status = ''active''
          AND cm.run_weekly_workflow = 1
          AND c.linkedin_id LIKE ''%linkedin.com%''
          AND c.full_name IS NOT NULL
        LIMIT 1
    ) c
    ON 1=1
    WHERE v.created_at >= NOW() - INTERVAL 7 DAY
',
    parameters_config = '{"success_reset_sql": "UPDATE candidate_marketing SET run_weekly_workflow = 0 WHERE candidate_id = :candidate_id"}'
WHERE id = 3;


-- ==========================================
-- 7. Disable problematic workflows (5, 6)
--    These reference non-existent tables (leads, outreach_email_recipients)
--    Re-enable after fixing their SQL queries
-- ==========================================

UPDATE automation_workflows_schedule SET enabled = 0 WHERE id IN (5, 6);


-- ==========================================
-- VERIFICATION QUERIES (run after migration)
-- ==========================================

-- Check Workflow 1 config:
-- SELECT id, name, recipient_list_sql, parameters_config FROM automation_workflows WHERE id = 1;

-- Check Workflow 3 config:
-- SELECT id, name, recipient_list_sql, parameters_config FROM automation_workflows WHERE id = 3;

-- Check triggers exist:
-- SHOW TRIGGERS LIKE 'candidate_marketing';

-- Check enabled schedules:
-- SELECT s.id, w.name, s.frequency, s.enabled, s.next_run_at
-- FROM automation_workflows_schedule s
-- JOIN automation_workflows w ON s.automation_workflow_id = w.id;

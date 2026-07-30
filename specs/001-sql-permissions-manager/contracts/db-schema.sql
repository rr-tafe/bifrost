-- Bifrost Database Schema Contract
-- Target: SQL Server 2019+
-- Applied: automatically on first application connection (if not already present)
-- This schema is append-only; no DROP or TRUNCATE is ever issued by the application.
--
-- The schema name used below is read from config.schema (default: dbo).
-- At runtime the application substitutes the configured schema name before executing.
-- The placeholder <schema> below represents that configured value.

-- ============================================================
-- Schema creation (skipped if schema is 'dbo')
-- ============================================================
-- If config.schema is not 'dbo', Bifrost creates the schema on first connection
-- using the pattern below (executed as dynamic SQL):
--
-- IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'<schema>')
--     EXEC sp_executesql N'CREATE SCHEMA [<schema>]';

-- ============================================================
-- Table: <schema>.Bifrost_audit_log
-- ============================================================
-- Immutable record of every permission change committed through Bifrost.
-- One row per permission changed per commit operation.
-- Shared across all administrators connecting to the same database.
IF NOT EXISTS (
    SELECT 1
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = N'<schema>' AND t.name = N'Bifrost_audit_log'
)
BEGIN
    -- Note: at runtime <schema> is replaced with the value from config.schema.
    -- The statement below is the template; the application executes it as dynamic SQL.
    EXEC sp_executesql N'
    CREATE TABLE [<schema>].[Bifrost_audit_log] (
        id               BIGINT         IDENTITY(1,1)  NOT NULL,
        administrator    NVARCHAR(128)                 NOT NULL,  -- SYSTEM_USER at commit time
        affected_user    NVARCHAR(128)                 NOT NULL,  -- database principal whose permission changed
        schema_name      NVARCHAR(128)                 NOT NULL,
        object_name      NVARCHAR(128)                 NOT NULL,
        permission_type  NVARCHAR(64)                  NOT NULL,  -- SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION
        action           NVARCHAR(16)                  NOT NULL,  -- GRANT | DENY | REVOKE
        previous_state   NVARCHAR(16)                  NOT NULL,  -- GRANT | DENY | NONE
        new_state        NVARCHAR(16)                  NOT NULL,  -- GRANT | DENY | NONE
        changed_at       DATETIME2(3)                  NOT NULL   DEFAULT (GETUTCDATE()),
        explanation      NVARCHAR(500)                 NULL,      -- auto-generated, e.g. "GRANT SELECT on dbo.Orders to alice"

        CONSTRAINT [PK_Bifrost_audit_log] PRIMARY KEY CLUSTERED (id),
        CONSTRAINT [CK_Bifrost_audit_log_action]         CHECK (action         IN (N''GRANT'', N''DENY'', N''REVOKE'')),
        CONSTRAINT [CK_Bifrost_audit_log_previous_state] CHECK (previous_state IN (N''GRANT'', N''DENY'', N''NONE'')),
        CONSTRAINT [CK_Bifrost_audit_log_new_state]      CHECK (new_state      IN (N''GRANT'', N''DENY'', N''NONE''))
    );

    CREATE NONCLUSTERED INDEX [IX_Bifrost_audit_log_changed_at]
        ON [<schema>].[Bifrost_audit_log] (changed_at DESC);

    CREATE NONCLUSTERED INDEX [IX_Bifrost_audit_log_affected_user]
        ON [<schema>].[Bifrost_audit_log] (affected_user, changed_at DESC);

    CREATE NONCLUSTERED INDEX [IX_Bifrost_audit_log_object]
        ON [<schema>].[Bifrost_audit_log] (schema_name, object_name, changed_at DESC);
    ';
END
GO

-- ============================================================
-- Notes on permissions required to use Bifrost
-- ============================================================
-- The connecting administrator account must have at minimum:
--   - VIEW DEFINITION on the target database (to read sys.objects, sys.schemas)
--   - SELECT on sys.database_permissions (implicit with VIEW DEFINITION)
--   - GRANT OPTION on object permissions they wish to manage
--   - INSERT on <schema>.Bifrost_audit_log (granted automatically if db_owner)
--   - ALTER on target objects (to set extended properties for descriptions)
--   - CREATE SCHEMA permission if config.schema does not already exist
--
-- db_owner or sysadmin role membership satisfies all of the above.

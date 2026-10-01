-- Large dataset for scale testing Bifrost (spec-01-data-layer.md section 11.3).
-- Adds to BifrostDev: 500 principals, 5,000 objects across 20 schemas, ~50,000
-- explicit permissions. Run via `dev/setup.sh --large` after the normal seed.
-- Idempotent: existing principals and objects are skipped; grants are only
-- applied once (guarded by a marker extended property).

USE BifrostDev;
GO
SET NOCOUNT ON;
GO

-- Principals: lg_user_0001 .. lg_user_0500 (users without login, type 'S')
DECLARE @i INT = 1, @name SYSNAME;
WHILE @i <= 500
BEGIN
    SET @name = CONCAT(N'lg_user_', RIGHT(CONCAT(N'000', @i), 4));
    IF USER_ID(@name) IS NULL
        EXEC (N'CREATE USER ' + N'[' + @name + N'] WITHOUT LOGIN');
    SET @i += 1;
END
GO

-- Schemas: lg01 .. lg20
DECLARE @s INT = 1, @schema SYSNAME;
WHILE @s <= 20
BEGIN
    SET @schema = CONCAT(N'lg', RIGHT(CONCAT(N'0', @s), 2));
    IF SCHEMA_ID(@schema) IS NULL
        EXEC (N'CREATE SCHEMA [' + @schema + N']');
    SET @s += 1;
END
GO

-- Objects: 4,000 tables, 500 views, 400 procedures, 100 scalar functions (5,000 total),
-- spread round-robin across the 20 schemas.
DECLARE @n INT = 1, @schema SYSNAME, @obj SYSNAME, @sql NVARCHAR(MAX);
WHILE @n <= 5000
BEGIN
    SET @schema = CONCAT(N'lg', RIGHT(CONCAT(N'0', ((@n - 1) % 20) + 1), 2));
    IF @n <= 4000
    BEGIN
        SET @obj = CONCAT(N'Table', RIGHT(CONCAT(N'000', @n), 4));
        SET @sql = N'CREATE TABLE [' + @schema + N'].[' + @obj + N'] (id INT PRIMARY KEY, val NVARCHAR(50))';
    END
    ELSE IF @n <= 4500
    BEGIN
        SET @obj = CONCAT(N'vw_', RIGHT(CONCAT(N'000', @n), 4));
        SET @sql = N'CREATE VIEW [' + @schema + N'].[' + @obj + N'] AS SELECT 1 AS one';
    END
    ELSE IF @n <= 4900
    BEGIN
        SET @obj = CONCAT(N'usp_', RIGHT(CONCAT(N'000', @n), 4));
        SET @sql = N'CREATE PROCEDURE [' + @schema + N'].[' + @obj + N'] AS SELECT 1 AS one';
    END
    ELSE
    BEGIN
        SET @obj = CONCAT(N'fn_', RIGHT(CONCAT(N'000', @n), 4));
        SET @sql = N'CREATE FUNCTION [' + @schema + N'].[' + @obj + N'] () RETURNS INT AS BEGIN RETURN 1; END';
    END

    IF OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@obj)) IS NULL
        EXEC (@sql);
    SET @n += 1;
END
GO

-- Permissions. Deterministic pseudo-random choice per (principal, object):
--   - principals 1-25 ("service accounts") get access to ~20% of objects
--   - everyone else gets ~1% of objects
--   - tables get one of SELECT/INSERT/UPDATE/DELETE (SELECT twice as likely),
--     views get SELECT, procedures and functions get EXECUTE
--   - about 2% of cells are DENY instead of GRANT
-- Grants are grouped by (object, permission, state) so each statement covers
-- many principals.
IF NOT EXISTS (
    SELECT 1 FROM sys.extended_properties
    WHERE class = 0 AND name = N'Bifrost_seed_large_permissions'
)
BEGIN
    DECLARE @cells TABLE (
        principal SYSNAME NOT NULL,
        securable NVARCHAR(300) NOT NULL,
        perm NVARCHAR(20) NOT NULL,
        state NVARCHAR(5) NOT NULL
    );

    INSERT INTO @cells (principal, securable, perm, state)
    SELECT
        dp.name,
        QUOTENAME(s.name) + N'.' + QUOTENAME(o.name),
        CASE
            WHEN o.type = 'U' THEN
                CASE ABS(CHECKSUM(dp.name, o.name, N'perm')) % 5
                    WHEN 0 THEN N'SELECT' WHEN 1 THEN N'SELECT' WHEN 2 THEN N'INSERT'
                    WHEN 3 THEN N'UPDATE' ELSE N'DELETE'
                END
            WHEN o.type = 'V' THEN N'SELECT'
            ELSE N'EXECUTE'
        END,
        CASE WHEN ABS(CHECKSUM(dp.name, o.name, N'deny')) % 50 = 0 THEN N'DENY' ELSE N'GRANT' END
    FROM sys.database_principals AS dp
    CROSS JOIN sys.objects AS o
    JOIN sys.schemas AS s ON s.schema_id = o.schema_id
    WHERE dp.name LIKE N'lg[_]user[_]%'
      AND s.name LIKE N'lg[0-9][0-9]'
      AND o.type IN ('U', 'V', 'P', 'FN')
      AND ABS(CHECKSUM(dp.name, o.name)) % 1000 <
          CASE WHEN CAST(RIGHT(dp.name, 4) AS INT) <= 25 THEN 200 ELSE 10 END;

    DECLARE @stmt NVARCHAR(MAX), @done INT = 0, @total INT;
    SELECT @total = COUNT(*) FROM (SELECT DISTINCT securable, perm, state FROM @cells) AS g;

    DECLARE grant_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT state + N' ' + perm + N' ON ' + securable + N' TO '
               + STRING_AGG(CAST(QUOTENAME(principal) AS NVARCHAR(MAX)), N', ')
        FROM @cells
        GROUP BY securable, perm, state;

    OPEN grant_cursor;
    FETCH NEXT FROM grant_cursor INTO @stmt;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC (@stmt);
        SET @done += 1;
        IF @done % 2000 = 0
            RAISERROR (N'  %d of %d grant statements', 0, 1, @done, @total) WITH NOWAIT;
        FETCH NEXT FROM grant_cursor INTO @stmt;
    END
    CLOSE grant_cursor;
    DEALLOCATE grant_cursor;

    EXEC sp_addextendedproperty @name = N'Bifrost_seed_large_permissions', @value = N'done';
END
GO

SELECT
    (SELECT COUNT(*) FROM sys.database_principals WHERE type IN ('S', 'U', 'G') AND principal_id > 4) AS principals,
    (SELECT COUNT(*) FROM sys.objects WHERE type IN ('U', 'V', 'P', 'FN', 'IF', 'TF') AND is_ms_shipped = 0) AS objects,
    (SELECT COUNT(*) FROM sys.database_permissions WHERE class = 1 AND minor_id = 0) AS explicit_permissions;
GO

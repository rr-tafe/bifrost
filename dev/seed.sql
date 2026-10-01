-- Seed data for the local Bifrost dev database.
-- Run via dev/setup.sh (sqlcmd -v ADMIN_PASSWORD=...). Safe to re-run.

IF DB_ID(N'BifrostDev') IS NULL
    CREATE DATABASE BifrostDev;
GO

-- SQL login Bifrost connects as in dev (stands in for a Windows admin account).
IF SUSER_ID(N'bifrost_admin') IS NULL
    CREATE LOGIN bifrost_admin WITH PASSWORD = N'$(ADMIN_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN bifrost_admin WITH PASSWORD = N'$(ADMIN_PASSWORD)';
GO

USE BifrostDev;
GO

IF USER_ID(N'bifrost_admin') IS NULL
BEGIN
    CREATE USER bifrost_admin FOR LOGIN bifrost_admin;
    ALTER ROLE db_owner ADD MEMBER bifrost_admin;
END
GO

-- Test principals (quickstart.md fixtures plus a few extras)
IF USER_ID(N'test_alice') IS NULL CREATE USER test_alice WITHOUT LOGIN;
IF USER_ID(N'test_bob')   IS NULL CREATE USER test_bob   WITHOUT LOGIN;
IF USER_ID(N'test_carol') IS NULL CREATE USER test_carol WITHOUT LOGIN;
IF USER_ID(N'report_svc') IS NULL CREATE USER report_svc WITHOUT LOGIN;
IF USER_ID(N'etl_svc')    IS NULL CREATE USER etl_svc    WITHOUT LOGIN;
GO

IF SCHEMA_ID(N'sales') IS NULL EXEC (N'CREATE SCHEMA sales');
GO

-- Test objects
IF OBJECT_ID(N'dbo.TestOrders') IS NULL
    CREATE TABLE dbo.TestOrders (id INT PRIMARY KEY, customer NVARCHAR(100), total DECIMAL(10, 2));
IF OBJECT_ID(N'dbo.TestProducts') IS NULL
    CREATE TABLE dbo.TestProducts (id INT PRIMARY KEY, name NVARCHAR(100));
IF OBJECT_ID(N'sales.Invoices') IS NULL
    CREATE TABLE sales.Invoices (id INT PRIMARY KEY, order_id INT, issued_at DATETIME2);
GO
CREATE OR ALTER VIEW dbo.TestOrdersView AS SELECT id, customer FROM dbo.TestOrders;
GO
CREATE OR ALTER PROCEDURE dbo.TestGetReport AS SELECT 1 AS result;
GO
CREATE OR ALTER FUNCTION dbo.TestOrderCount() RETURNS INT AS BEGIN RETURN (SELECT COUNT(*) FROM dbo.TestOrders); END;
GO

-- Starting permissions so the matrix has GRANT and DENY cells to show
GRANT SELECT ON dbo.TestOrders TO test_alice;
GRANT SELECT, INSERT ON dbo.TestProducts TO test_bob;
DENY  DELETE ON dbo.TestOrders TO test_bob;
GRANT SELECT ON dbo.TestOrdersView TO report_svc;
GRANT EXECUTE ON dbo.TestGetReport TO report_svc;
GRANT SELECT, INSERT, UPDATE ON sales.Invoices TO etl_svc;
GO

-- One existing description (MS_Description extended property)
IF NOT EXISTS (
    SELECT 1 FROM sys.extended_properties
    WHERE major_id = OBJECT_ID(N'dbo.TestProducts') AND minor_id = 0 AND name = N'MS_Description'
)
    EXEC sp_addextendedproperty
        @name = N'MS_Description', @value = N'Product catalogue used by test orders.',
        @level0type = N'SCHEMA', @level0name = N'dbo',
        @level1type = N'TABLE',  @level1name = N'TestProducts';
GO

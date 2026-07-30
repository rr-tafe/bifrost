# Graph Report - .  (2026-07-30)

## Corpus Check
- Corpus is ~44,287 words - fits in a single context window. You may not need a graph.

## Summary
- 164 nodes · 192 edges · 12 communities
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 15 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Bash Scripts & Prerequisites
- SpecKit Skills & Pipeline
- Config JSON Schema
- Tag Examples & References
- Tag Store Rules
- Config Schema Properties
- Permission Data Model
- Feature Specification & User Stories
- Tags JSON Schema
- UI & Canvas Architecture
- Config Schema Field
- DB Layer & pyodbc

## God Nodes (most connected - your core abstractions)
1. `Bifrost Constitution` - 19 edges
2. `SQL Server Permissions Manager (Bifrost)` - 8 edges
3. `notes` - 7 edges
4. `required` - 6 edges
5. `port` - 6 edges
6. `schema` - 6 edges
7. `user_tags` - 5 edges
8. `object_tags` - 5 edges
9. `SpecKit Tasks` - 5 edges
10. `PermissionAssignment (in-memory matrix cell)` - 5 edges

## Surprising Connections (you probably didn't know these)
- `SpecKit Tasks to Issues` --references--> `Bifrost Constitution`  [EXTRACTED]
  .claude/skills/speckit-taskstoissues/SKILL.md → .specify/memory/constitution.md
- `Plan Template` --references--> `Canvas Virtual Scrolling (800k cells rendering)`  [INFERRED]
  .specify/templates/plan-template.md → specs/001-sql-permissions-manager/plan.md
- `SpecKit Analyze` --references--> `Bifrost Constitution`  [EXTRACTED]
  .claude/skills/speckit-analyze/SKILL.md → .specify/memory/constitution.md
- `SpecKit Checklist` --references--> `Bifrost Constitution`  [EXTRACTED]
  .claude/skills/speckit-checklist/SKILL.md → .specify/memory/constitution.md
- `SpecKit Checklist` --references--> `Checklist Template`  [EXTRACTED]
  .claude/skills/speckit-checklist/SKILL.md → .specify/templates/checklist-template.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **SpecKit End-to-End Pipeline** — _claude_skills_speckit_specify_skill_speckit_specify, _claude_skills_speckit_clarify_skill_speckit_clarify, _claude_skills_speckit_plan_skill_speckit_plan, _claude_skills_speckit_tasks_skill_speckit_tasks, _claude_skills_speckit_analyze_skill_speckit_analyze, _claude_skills_speckit_implement_skill_speckit_implement, _claude_skills_speckit_converge_skill_speckit_converge [EXTRACTED 1.00]
- **Bifrost Constitution Principles (I–VIII)** — _specify_memory_constitution_test_coverage, _specify_memory_constitution_security_authentication, _specify_memory_constitution_simple_architecture, _specify_memory_constitution_clean_code, _specify_memory_constitution_simple_ux, _specify_memory_constitution_minimal_dependencies, _specify_memory_constitution_ui_accessibility, _specify_memory_constitution_input_validation [EXTRACTED 1.00]
- **Requirements Quality Validation Group** — _claude_skills_speckit_specify_skill_speckit_specify, _claude_skills_speckit_clarify_skill_speckit_clarify, _claude_skills_speckit_checklist_skill_speckit_checklist, unit_tests_for_english [INFERRED 0.85]
- **Permission Matrix Core Data Model** — specs_001_sql_permissions_manager_data_model_database_user, specs_001_sql_permissions_manager_data_model_database_object, specs_001_sql_permissions_manager_data_model_permission_state, specs_001_sql_permissions_manager_data_model_permission_assignment, specs_001_sql_permissions_manager_data_model_staged_change [EXTRACTED 1.00]
- **Commit and Audit Pipeline** — specs_001_sql_permissions_manager_data_model_staged_change, specs_001_sql_permissions_manager_data_model_audit_entry, specs_001_sql_permissions_manager_spec_staged_commit_pattern, specs_001_sql_permissions_manager_plan_src_db_module [EXTRACTED 1.00]
- **SpecKit Spec-Design-Develop Artifact Cycle** — _specify_templates_spec_template_spec_template, _specify_templates_plan_template_plan_template, _specify_templates_tasks_template_tasks_template, specs_001_sql_permissions_manager_spec_sql_permissions_manager [INFERRED 0.85]

## Communities (12 total, 0 thin omitted)

### Community 0 - "Bash Scripts & Prerequisites"
Cohesion: 0.10
Nodes (12): check-prerequisites.sh script, check_dir(), check_file(), get_feature_paths(), get_repo_root(), has_jq(), _persist_feature_json(), resolve_specify_init_dir() (+4 more)

### Community 1 - "SpecKit Skills & Pipeline"
Cohesion: 0.13
Nodes (24): SpecKit Analyze, SpecKit Checklist, SpecKit Clarify, SpecKit Constitution, SpecKit Converge, SpecKit Implement, SpecKit Plan, SpecKit Specify (+16 more)

### Community 2 - "Config JSON Schema"
Cohesion: 0.10
Nodes (20): windows, description, enum, type, description, minLength, type, default (+12 more)

### Community 3 - "Tag Examples & References"
Cohesion: 0.12
Nodes (18): critical, finance, readonly, tier1, tier2, alice, bob, dbo.GetReportData (+10 more)

### Community 4 - "Tag Store Rules"
Cohesion: 0.12
Nodes (15): An empty tags.json is valid: { \"user_tags\": {}, \"object_tags\": {} }, If tags.json is missing, the application creates it with empty collections on first tag write., object_tags, Tag keys in object_tags use the format 'schema_name.object_name'., Tag keys in user_tags must match sys.database_principals.name exactly., Tags are case-preserved but duplicate detection is case-insensitive., Tags are never synced to SQL Server; they exist only on the local machine., user_tags (+7 more)

### Community 5 - "Config Schema Properties"
Cohesion: 0.15
Nodes (12): auth_type, database, port, schema, server, additionalProperties, description, examples (+4 more)

### Community 6 - "Permission Data Model"
Cohesion: 0.27
Nodes (10): AuditEntry (immutable committed change record), Configuration (local config.json), DatabaseObject Entity, DatabaseUser Entity, PermissionAssignment (in-memory matrix cell), PermissionState Enum (GRANT/DENY/NONE), StagedChange (pending permission change), TagStore (local tags.json) (+2 more)

### Community 7 - "Feature Specification & User Stories"
Cohesion: 0.29
Nodes (10): SQL Server Permissions Manager (Bifrost), Staged Commit Pattern (stage locally, batch apply), US1: View & Toggle Permission Matrix, US1b: Object View - Manage Access by Object+Permission, US2: Search, Filter & Sort, US3: Tag and Metadata Management, US4: Audit Log Review, US5: CSV Report Export (+2 more)

### Community 8 - "Tags JSON Schema"
Cohesion: 0.32
Nodes (8): items, type, uniqueItems, description, pattern, type, additionalProperties, additionalProperties

### Community 9 - "UI & Canvas Architecture"
Cohesion: 0.29
Nodes (7): Plan Template, Spec Template, Tasks Template, SpecKit Workflow Configuration, Canvas Virtual Scrolling (800k cells rendering), src/ui/ Module (Tkinter UI layer), Research Decision: Canvas Virtual Scrolling

### Community 10 - "Config Schema Field"
Cohesion: 0.33
Nodes (6): schema, default, description, minLength, pattern, type

### Community 11 - "DB Layer & pyodbc"
Cohesion: 0.50
Nodes (4): pyodbc 5.x SQL Server Driver, src/db/ Module (DB access layer), src/services/ Module (Business logic layer), Research Decision: pyodbc over pymssql

## Knowledge Gaps
- **67 isolated node(s):** `common.sh script`, `$schema`, `title`, `description`, `type` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `properties` connect `Config JSON Schema` to `Config Schema Field`, `Config Schema Properties`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `properties` connect `Tag Examples & References` to `Tag Store Rules`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Why does `object_tags` connect `Tag Examples & References` to `Tags JSON Schema`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **What connects `common.sh script`, `$schema`, `title` to the rest of the system?**
  _67 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Bash Scripts & Prerequisites` be split into smaller, more focused modules?**
  _Cohesion score 0.09788359788359788 - nodes in this community are weakly interconnected._
- **Should `SpecKit Skills & Pipeline` be split into smaller, more focused modules?**
  _Cohesion score 0.13043478260869565 - nodes in this community are weakly interconnected._
- **Should `Config JSON Schema` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._
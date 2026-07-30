# Bifrost Constitution

## Core Principles

### I. Test Coverage (NON-NEGOTIABLE)

All production code MUST have accompanying unit tests. Test coverage MUST remain above 80% at
all times, measured per module and enforced in CI. Tests MUST be written before implementation
is considered complete. No code is mergeable if it drops overall coverage below the threshold.

**Rationale**: Coverage gates catch regressions early and enforce the discipline of writing
testable, well-scoped code. The 80% floor is a minimum, not a target — aim higher.

### II. Security & Authentication (NON-NEGOTIABLE)

Secrets (API keys, credentials, tokens, passwords) MUST NEVER be committed to version control.
Use environment variables or a secrets manager; `.env` files MUST be listed in `.gitignore`.
All application endpoints and authenticated surfaces MUST require valid credentials before
granting access. Pre-commit hooks SHOULD scan for accidental secret inclusion.

**Rationale**: A single committed secret can compromise the entire system and its users. There
is no recovery path that justifies skipping this rule.

### III. Simple Architecture

The codebase MUST favor the simplest design that solves the problem. Abstractions MUST only be
introduced when they eliminate concrete, present duplication — not hypothetical future reuse.
No repository pattern, service-locator, plugin system, or indirection layer may be added unless
a specific, documented need exists. When in doubt, choose the flat, direct approach.

**Rationale**: Premature abstraction creates maintenance burden and cognitive overhead that
outlasts the original developer. Three similar lines are better than a premature helper.

### IV. Clean Code

Code MUST be self-documenting through clear naming. Functions and classes MUST have a single,
well-defined responsibility. Comments MUST explain WHY, never WHAT. Dead code and unused
imports MUST be removed before merge. All code MUST pass the project linter (flake8 or ruff)
with zero warnings. Code MUST prefer explicit, readable expressions over clever one-liners;
comprehension MUST NOT be sacrificed for brevity. When a multi-line form and a compact form
are equally correct, the form a new reader can parse without re-reading MUST be chosen.

**Rationale**: Readable code is cheaper to maintain, review, and extend. Self-explanatory
identifiers eliminate entire categories of stale documentation. Clever one-liners optimise
for the writer's moment, not the reader's hour.

### V. Simple UX

The Tkinter interface MUST minimise the number of steps required to complete any primary user
task. Every interactive element MUST have a clear label or tooltip. Error messages MUST be
actionable — they MUST tell the user what went wrong and how to recover. The UI layout MUST
remain usable when the window is resized (responsive geometry management via grid or pack with
weight configuration). No decorative widgets may be added that do not serve a functional
purpose.

**Rationale**: Desktop users expect immediate, predictable responses. Cluttered or confusing
UIs lead to user error and support burden regardless of backend correctness.

### VI. Minimal Dependencies

The project MUST default to the Python standard library and Tkinter. A third-party package may
only be added if: (a) it replaces non-trivial custom code, AND (b) it is actively maintained
with a permissive licence, AND (c) its addition is documented in the plan with explicit
justification. Transitive dependencies MUST be evaluated. No dependency may be added solely
for convenience if the stdlib alternative is reasonably ergonomic.

**Rationale**: Each dependency is a maintenance liability and a potential supply-chain risk.
Minimal dependency graphs are easier to audit, package, and distribute as desktop applications.

### VII. UI Accessibility

Every interactive element (buttons, entries, checkboxes, listboxes, menus) MUST be fully
keyboard-navigable without requiring a mouse. Tab order MUST follow a logical, top-to-bottom
left-to-right reading flow; custom tab sequences MUST be explicitly set when the default
differs. All interactive widgets MUST be reachable via Tab/Shift-Tab and activatable via
Enter or Space. Keyboard shortcuts for primary actions MUST be documented in the UI (e.g.,
via menu labels or tooltips). Focus indicators MUST remain visible — the default Tkinter
highlight MUST NOT be suppressed.

**Rationale**: Keyboard-only navigation is required by users with motor impairments and
power users alike. Building it in from the start is far cheaper than retrofitting it later.

### VIII. Input Validation

All data received from user input fields, file reads, or external sources MUST be validated
before use. Validation MUST occur at the boundary where data enters the application, not
inside business logic. Invalid input MUST result in a clear, user-facing error message (see
Principle V) and MUST NOT propagate into the system. Numeric fields MUST reject non-numeric
input. Length and range constraints MUST be enforced. File paths provided by the user MUST
be validated for existence and read/write permissions before access is attempted.

**Rationale**: Unvalidated input is the root cause of a wide class of bugs and security
vulnerabilities. Validating at the boundary keeps business logic clean and prevents
confusing internal errors from surfacing to users.

## Security Requirements

- All secrets MUST be loaded from environment variables at runtime; never hardcoded.
- `.env`, `*.pem`, `*.key`, and credential files MUST be listed in `.gitignore` before any
  secret-bearing file is created.
- Authentication checks MUST be enforced at the entry point of every protected operation,
  not delegated to callers.
- Input validation (Principle VIII) is a security control; bypassing it in any code path is
  a security defect, not a convenience shortcut.
- Dependency versions MUST be pinned in `requirements.txt` to prevent silent supply-chain
  upgrades.
- Security-sensitive changes (auth, secrets handling, credential storage, validation) MUST be
  explicitly called out in PR descriptions and reviewed by at least one additional reviewer.

## Development Workflow

- Every feature MUST have a corresponding spec before implementation begins (`/speckit-specify`).
- Test tasks are **mandatory** for this project — the tasks template note marking them optional
  does not apply here. Coverage gates enforce this at CI level.
- Pre-commit hooks MUST be configured to run: linting, secret scanning, and the test suite.
- Complexity violations of Principle III MUST be documented in the plan's Complexity Tracking
  table with a written justification before the abstraction is introduced.
- The Tkinter UI MUST be manually smoke-tested on the target platform before any release tag,
  including a keyboard-only navigation pass to verify Principle VII compliance.
- Input validation MUST be implemented and tested as part of the Foundational phase, not
  deferred to later stories.

## Governance

This constitution supersedes all other practices, conventions, and verbal agreements within
the Bifrost project. Where a conflict exists between this document and any other guideline,
this document takes precedence.

**Amendment procedure**: Any change to the constitution requires: (1) a written proposal
describing the change and its rationale, (2) review and approval by the project lead, and
(3) a version bump per the semantic versioning policy below. The amended constitution MUST
be propagated to all dependent templates via `/speckit-constitution`.

**Versioning policy**:
- MAJOR — principle removed, redefined, or governance structure altered incompatibly.
- MINOR — new principle or section added, or existing guidance materially expanded.
- PATCH — clarification, wording fix, or non-semantic refinement.

**Compliance review**: Constitution compliance MUST be verified at the Constitution Check gate
in every implementation plan (`/speckit-plan`) before Phase 0 research begins, and re-checked
after Phase 1 design. Any deviation detected post-merge MUST be logged as a bug and resolved
in the next sprint.

**Version**: 1.1.0 | **Ratified**: 2026-07-14 | **Last Amended**: 2026-07-14

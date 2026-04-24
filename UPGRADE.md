# Termpipe Workspace Upgrade Plan

## Infrastructure We Have (Don't Underestimate This)

Before listing gaps, the full stack needs to be understood:

**kc-bus** — Production-grade local IPC bus over Unix socket. Zero deps.
Sequence numbers, history (tail / --after N), binary/file payloads,
wait/poll with timeouts, stdlib SDKs for Python/Node/Go/shell. Topics
are live pub/sub channels; `--after N` enables reliable resume from
any point. This is not internal plumbing — it's the event backbone.

**gtt (GreaterTouchTool)** — Full desktop automation engine. Window
management, input injection (type/key/click), app launch, hotkeys,
macros, text expansion. Critically: real-time event subscriptions
(--sub-window, --sub-application, --sub-workflow, --sub-all), vision +
OCR + AI screen queries, AT-SPI accessibility tree scanning. gtt +
kc-bus = a full event-driven RPA stack.

**context-core** — LTM + file-change tracking per workspace. Per-workspace
SQLite with work_sessions, file_changes (unified diffs), file_baselines
(compressed snapshots). Full diff-replay restore to any past session.
Registered via workspace_id ↔ folder_path in registry.db. Loaded each
session via context-core:session() — triggered by the boot directive
emitted from list_tools / boot.

**termpipe-mcp workspace tools** — task.md / implementation_plan.md /
walkthrough.md as versioned artifacts in SQLite + disk + bus. HITL
approval gate (draft → pending_approval → approved/rejected) via
kc-bus blocking poll. list_tools(cwd) bootstraps the whole stack:
writes current_workspace, calls workspace_resume() to re-hydrate bus,
runs _reconcile_tasks() to auto-close tasks referenced in git commits.

**The wiring principle:** Not every connection needs to be Python source
code. The right architecture uses:
  (a) Core tool upgrades — new Python tools / DB schema changes
  (b) Bus-level bridges — kc-bus subscriber scripts/daemons that react
      to events and stamp/link records across systems
  (c) LTM operations — add_memory, workspace_doc_update to make
      architectural decisions and one-off links permanent

---

## The Core Problem

The task system is a markdown checklist. A task looks like this:

    - [ ] Implement auth module <!-- id: 3 -->

That's it. No description, no priority, no definition of done, no
dependencies, no queryability. task.md is the source of truth, which
means the source of truth is a regex-parsed text file.

Meanwhile: context-core tracks every file change (unified diffs,
session_nums, baselines). A task gets marked [x] and the connection
to what was actually changed to accomplish it evaporates.

The bus publishes task mutations to termpipe.workspace.task on every
write — the signal is already there. It just isn't being acted on.

---

## What Atlas Gets Right (cyanheads/atlas-mcp-server)

Atlas uses Neo4j for tasks but the schema ideas are what matter:

- `completion_requirements` — explicit, measurable success criteria.
  The most important missing field. Without it, "done" is whatever
  Claude decides it is.
- `output_format` — forces declaration of what will be produced
  ("Python module at src/foo.py", "markdown report with these sections")
- `task_type` — research / implementation / test / review / config / docs / fix
- `priority` — critical / high / medium / low
- `depends_on[]` — task IDs that must be done first, with enforcement
- `tags[]` — for filtering and grouping

Atlas has zero HITL approval. Termpipe wins there completely.

---

## Upgrade 1 — Structured `tasks` Table  [CORE / Source Change]

Add to `_db.py` alongside the existing `artifacts` table:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT NOT NULL,
    description             TEXT,
    priority                TEXT DEFAULT 'medium',
    status                  TEXT DEFAULT 'todo',
    task_type               TEXT,
    completion_requirements TEXT,
    output_format           TEXT,
    depends_on              TEXT DEFAULT '[]',   -- JSON array of task IDs
    tags                    TEXT DEFAULT '[]',   -- JSON array of strings
    notes                   TEXT,
    session_done            INTEGER,             -- context-core session_num ← THE WIRE
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
)
```

task.md becomes auto-rendered from this table. DB is source of truth.
Markdown is preserved for bus publishing and human readability.

---

## Upgrade 2 — New Tools  [CORE / Source Change]

Replace `workspace_task_update(action=add)` with:

`workspace_task_create(cwd, title, description, priority, task_type,
  completion_requirements, output_format, depends_on=[], tags=[])`
→ Creates structured task, returns ID, renders task.md.

`workspace_task_bulk_create(cwd, tasks[])`
→ Atomic multi-task seed. Called at workspace_init time.

`workspace_task_query(cwd, status=None, priority=None, task_type=None)`
→ Filter/list from DB. "What's blocked?" "What's critical and not started?"

---

## Upgrade 3 — Dependency Enforcement  [CORE / Source Change]

Before any transition to in_progress / needs_review / done:
check all depends_on IDs have status=done.

If not, return:
    BLOCKED: task [5] "Implement auth module" must be done first.

This makes depends_on[] load-bearing, not decorative.

---

## Upgrade 4 — `needs_review` + Task-Level HITL  [CORE / Source Change]

Add `needs_review` as a valid task status. Extend the existing
plan-level approval pattern down to individual tasks:

`workspace_task_request_review(cwd, task_id, message=None)`
→ Sets status=needs_review
→ Publishes to termpipe.workspace.task_review_request
→ Payload includes completion_requirements + output_format so the
  human knows exactly what to verify

`workspace_await_task_approval(cwd, task_id)`
→ Same kc-bus blocking poll pattern as workspace_await_approval()
→ Returns APPROVED | FEEDBACK: <text> | REJECTED

---

## Upgrade 5 — The Missing Wire: Tasks ↔ context-core  [BUS BRIDGE]

This is NOT a Python source change. It's a kc-bus subscriber.

A small bridge script subscribes to termpipe.workspace.task.
When it sees status=done in the payload, it:
  1. Reads ws_id from the payload
  2. Opens ~/.context-core/workspaces/ws_<id>/workspace.db
  3. SELECT MAX(session_num) FROM work_sessions
  4. Opens the termpipe workspace.db
  5. UPDATE tasks SET session_done=<session_num> WHERE id=<task_id>

This unlocks:
  "Show me all files changed to complete task 3"
  → SELECT * FROM file_changes WHERE session_num = tasks.session_done
  "Restore to before task 5 was started"
  → restore_to(tasks[4].session_done)
  "What tasks were worked on this session?"
  → SELECT * FROM tasks WHERE session_done = current_session

Implementation: small Python script using kc-bus Python SDK (3 lines),
run as a systemd user service or launched by gttd / workspace_init.

---

## Upgrade 6 — Richer `list_tools` / `boot` Output  [CORE / Source Change]

`_open_tasks_summary()` currently shows only [ ] items as plain text.
Pull from the tasks table instead:

    📋 TASKS  (3 todo · 1 in_progress · 1 needs_review · 0 blocked)

      ⏳ NEEDS REVIEW
        [4] Implement auth module
            verify: unit tests pass, JWT returned per spec

      🔄 IN PROGRESS
        [3] Set up database schema  [high · implementation]

      🚫 BLOCKED
        [6] Write integration tests  ← waiting on [3], [4]

      📝 TODO  (2 remaining)
        [1] Research OAuth providers  [medium · research]
        [2] Design API contract  [high · review]

---

## Upgrade 7 — `completion_requirements` on `workspace_init`  [CORE]

Add optional `completion_requirements` param to `workspace_init`.
Forces declaration of done for the entire goal upfront.
Store in the plan artifact header.

---

## What Stays Exactly As-Is

- Three-artifact structure (task / plan / walkthrough)     ✓
- workspace_resume() bus re-hydration on list_tools        ✓
- _reconcile_tasks() git commit auto-close                 ✓  (expand)
- Plan-level HITL gate (draft→pending→approved/rejected)   ✓
- kc-bus raw socket approach, no SDK dependency in core    ✓
- context-core:session() bootstrap directive pattern       ✓

---

## Implementation Order

1.  Add `tasks` table to `_db.py`
2.  `workspace_task_create()` tool
3.  Dependency enforcement in status transitions
4.  Auto-render task.md from tasks table
5.  `workspace_task_query()` tool
6.  `needs_review` status + task-level HITL tools
7.  Richer `_open_tasks_summary()` from tasks table
8.  `workspace_task_bulk_create()` + wire into `workspace_init`
9.  `completion_requirements` on `workspace_init`
10. Bus bridge: tasks ↔ context-core session_done watcher

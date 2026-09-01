# pTLC UniLab domain package

This package projects the existing PlatformUI device and operation catalog into
UniLab OS without replacing either system's runtime authority.

## Authority boundaries

- PlatformUI remains authoritative for device semantics, root-operation
  execution, the existing `ResourceGate`, and the full-operation `robot` plus
  `station:rail` lock.
- UniLab OS remains authoritative for workflow scheduling, typed material
  identity/location, and host-side lineage commits.
- MoveIt remains authoritative for CR5 kinematics, planning, collision state,
  and trajectory display. PlatformUI GLB nodes are read-only scene and
  attachment references; they do not replace the MoveIt robot model.
- A transfer performs exactly one PlatformUI root-operation submission. An
  unknown result is surfaced for reconciliation and is never retried as a new
  physical command.

## Typed station-operation Actions

The longest executable flow never exposes the generic
`run_station_operation_v4(operation_name, inputs_json)` shape on its canvas.
Its seven station roots are generated as fixed, typed Actions such as
`photoscrape_before_photo_capture(sample_id, save_dir, timeout_s)`. Parameter
names, defaults, titles, and descriptions come from the original operation
YAML. The adapter filters omitted optional values, encodes the fields, and
then delegates once to the unchanged PlatformUI operation VM. The generic
entry point remains available for compatibility, but is not used by the
longest flow.

## Generated longest-flow variants

All Python sources are generated from PlatformUI's
`config/recipes/parallel_v1.yaml` and operation YAML; they carry a `DO NOT
EDIT` header. The UniLab-only material/transport bridge lives in the exporter
templates, not in the generated workflow files.

- `ptlc_parallel_v4`: every selected station operation is a fixed-name,
  typed Action with per-field titles and defaults.
- `ptlc_parallel_station_operation_v1`: every selected station operation uses
  the same compatibility Action, `run_station_operation_v4`, with
  `operation_name` and `inputs_json`.
- `ptlc_parallel_operation_review_v1`: every recipe segment is a child
  Workflow that can be expanded according to scheme 1; source nodes are
  disabled review projections, loops stop at their boundary, and the segment
  root is the sole enabled execution node.
- `ptlc_parallel_segments_v1`: the recipe's twelve operation segments are
  executable child Workflows with explicit portable-material inputs and
  outputs. The source sidecar `config/recipes/parallel_v1.materials.yaml`
  distinguishes UniLab `ResourceSlot` identities from station-managed liquids
  whose inventory remains authoritative in PlatformUI.
- `ptlc_parallel_segments_v2`: each of the same twelve material-aware runtime
  children contains one disabled, expandable `*_operation_view_v2` plus one
  enabled root-operation submission. A `run_script` is represented as a child
  Workflow instead of recursively inlining its implementation.

Regenerate or verify them with:

```bash
PYTHONPATH=. python tools/generate_unilab_domain.py
PYTHONPATH=. python tools/export_unilab_workflow_variants.py --check
```

The first command is the complete PlatformUI-to-UniLab export. It regenerates
the action/device facade, direct operation views, runtime segments, parent
flows, manifests, and `package.yaml`; generated Python is never edited by hand.

## Operation-to-action review workflows

`ptlc_parallel_operation_review_v1` is a separate, non-replacing review form
of the PlatformUI `parallel_v1` longest flow.  It composes twelve child
workflows (`af0` and `s1`–`s11`).  Expanding a child shows its source action
and control projection, including `if`/`elif`, exception branches, HITL, local
resource windows, assignments and comments. Each unique child operation is
expanded once per review segment; repeated `run_script` call sites become
disabled reference markers. `for`/`while`/`repeat` are visible as disabled
boundary markers, but their bodies are deliberately not expanded.

Every projected source node is statically `disabled`; the only enabled action
in each child is `material.run_operation_review_v1`.  That action submits the
unchanged PlatformUI segment root once, so its existing root `ResourceGate`,
branch decisions, loops and HITL remain authoritative.  The projection must
never be enabled action-by-action.  Its reproducible source/count manifest is
`eit_ptlc/unilab_domain/generated/platformui_operation_review.v1.yaml`.

The source audit still traverses 70 operation documents and 1,402 action-call
occurrences, including loop bodies, so provenance remains complete.  The UI
projection stops at three loop boundaries, de-duplicates 41 repeated child
operation references, and currently emits 2,270 disabled action nodes across
the twelve review children.  These source-audit figures
supersede the earlier 69/409 estimate, which did not traverse
`elif`/catch/HITL-nested statements.

The v2 hierarchy is the runnable review form intended for the Workbench.
Its 69 `*_operation_view_v2` workflows contain only nodes physically present
in one operation document. A direct `run_script` becomes a disabled nested
view, while loops remain one disabled boundary marker. The corresponding 12
`*_runtime_v2` workflows show that hierarchy but submit only the unchanged
PlatformUI segment root, so display expansion cannot duplicate physical work.

## Twelve material-aware operation segments

`ptlc_parallel_segments_v1` composes twelve generated `*_material_v1` child
workflows. Each child first calls its corresponding `*_action_review_v1`
workflow, so the original PlatformUI root operation remains the sole physical
execution boundary. Only after that root returns `DONE` does the child commit
the same material identity at its new mount or add a lineage edge.

The portable lineage is `source sample vial -> pTLC plate -> powder collector
-> collection vial`. Sampling wash/rinse solvent, the four development
solvents, the prepared bath, and collection elution solvent are listed in the
material contract but remain managed by PlatformUI's liquid ledger. This
avoids two systems deducting the same stationary reagent.

## Local Theia Workbench

Use a Python environment containing this repository's declared dependencies.
The shared UniLab environment can be used for OS; PlatformUI should normally be
installed in its own environment with `python -m pip install -e .`.

Start the Workbench first so Workspace Backend and Edge can finish their
fixed-point compilation while the source tree is stable:

```bash
source /Users/dp/miniforge3/envs/unilab/setup.zsh
node /Users/dp/Design_projects/Uni-Lab-Core-worktrees/PTLC-local-20260817/uni-lab-fe/apps/workbench/scripts/start-workbench.mjs \
  --workspace /Users/dp/Design_projects/pTLC_platformUI \
  --os-project /Users/dp/Design_projects/Uni-Lab-Core-worktrees/PTLC-platformUI-os-20260818 \
  --python-env /Users/dp/miniforge3/envs/unilab \
  --port 3134
```

In **Environment Management**, start OS with
`deployment/graphs/ptlc-platformui-local-debug.json`. After OS reports ready, start the
PlatformUI simulator on the contract endpoint:

```bash
EIT_MODE=sim python -m uvicorn eit_ptlc.runtime.bootstrap:app \
  --host 127.0.0.1 --port 18080
```

For real hardware, select the separate
`deployment/graphs/ptlc-platformui-real.json` graph. Its eleven proxy devices
target the production PlatformUI API at `http://127.0.0.1:18080` without the
`/api/sim` suffix. The CR5 remains directly controlled by PlatformUI:
`community.eit_ptlc.robot` keeps `standard_execution_backend: platformui`;
`unilab_arm_cr5` supplies the six-axis model/MoveIt description and is not a
replacement graph device class. After checking the hardware addresses in
`config/app.yaml`, start PlatformUI with:

```powershell
& "D:\miniforge3\envs\szlab-unilab\python.exe" eit_ptlc/main.py --real --no-browser
```

Before enabling motion, verify the PLC OPC UA, CR5 TCP, camera, PALLASVision
and water-level endpoints from `config/app.yaml` and physically clear the work
cell. Keep the local-debug graph on `/api/sim`; do not repoint it to hardware.

Verify the server and the source recipe before submitting from UniLab:

```bash
curl http://127.0.0.1:18080/api/health
curl http://127.0.0.1:18080/api/scripts
```

The main `EIT_MODE=sim` server uses PlatformUI's persistent material ledger.
Seed that ledger before a clean full-flow validation (these are not the
separate `/api/sim/*` sandbox endpoints):

```bash
curl -X POST http://127.0.0.1:18080/api/materials/magazine \
  -H 'Content-Type: application/json' \
  -d '{"magazine":"feed","count":10}'
curl -X POST http://127.0.0.1:18080/api/materials/magazine \
  -H 'Content-Type: application/json' \
  -d '{"magazine":"waste","count":1}'
curl -X POST http://127.0.0.1:18080/api/materials/mark \
  -H 'Content-Type: application/json' \
  -d '{"kind":"collector","plate":1,"state":"FRESH"}'
curl -X POST http://127.0.0.1:18080/api/materials/mark \
  -H 'Content-Type: application/json' \
  -d '{"kind":"bottle","plate":1,"state":"FRESH"}'
for bottle in solvent_1 solvent_2 solvent_3 solvent_4 eluent; do
  curl -X POST http://127.0.0.1:18080/api/materials/bottle \
    -H 'Content-Type: application/json' \
    -d "{\"bottle\":\"${bottle}\",\"volume_ml\":1000}"
done
```

Confirm `summary.collector.fresh == 6`, `summary.bottle.fresh == 6`, and
`magazines[feed].count > 0` plus `magazines[waste].count > 0` with
`GET /api/materials`. Re-run the seed commands when a previous simulation has
consumed those records.

A newly created isolated `/api/sim` session automatically seeds one `waste`
support plate because the real FeedLift A22 preflight requires the waste-stack
proximity signal. Sessions created with `adopt: true` do not receive this
synthetic seed; they preserve the adopted live inventory exactly.

The graph's PlatformUI proxy devices all point to
`http://127.0.0.1:18080`. In Workbench select
`并行全流程 v2（分层展示 + 原子运行，12 段）` and use the generated JSON inputs; the
default sample uses tank 1. Human-confirm nodes are still handled by the
PlatformUI VM and its existing debug/HITL endpoints.

Starting PlatformUI after Edge is deliberate: its simulator recorder writes
under `eit_ptlc/var`, while the first Workspace/Edge compilation requires a
stable source tree.

## Validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  eit_ptlc/tests/test_unilab_domain_v4_offline.py \
  eit_ptlc/tests/test_unilab_operation_review_offline.py \
  eit_ptlc/tests/test_unilab_three_d_facade_offline.py

PYTHONPATH=. python tools/generate_unilab_domain.py
```

The generated proxy surface is fixed at 11 devices, 93 atomic PlatformUI
actions, and seven typed station-operation Action façades used by the longest
flow.
The default package currently exports 85 workflows: one transport workflow,
69 child-first operation views, 12 hierarchical runtime v2 segments, and the
three current conversion entries (typed Action, generic Action, hierarchical
v2). The 29-workflow pre-v2 registration remains reproducibly generated as
`package.legacy.yaml`, while all legacy Python and manifests stay unchanged.
This avoids validating both heavy review projections on every local startup.
Existing PlatformUI recipes and operations remain unchanged; only generated
UniLab projections and the sidecar material contract are added around them.

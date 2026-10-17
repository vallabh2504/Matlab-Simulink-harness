# Codex CLI command roles

`scripts/codex_command_adapter.py` lets the harness run builder, reviewer and repair
roles through an npm-installed [Codex CLI](https://github.com/openai/codex) and
Node.js. Supply your own model, Python, Node, CLI entry script, the CLI's active
configuration home and an evidence folder outside the project. The package contains
no credentials or installation paths.

`--codex-home` selects the existing rollout directory for provenance inspection.
It does not set `CODEX_HOME`, move credentials/configuration or change the child's
environment. Supply the home already used by your actual CLI. If you explicitly
configure another home through the host environment, supply that same active home.
An incorrect lookup path fails provenance rather than inventing a model identity.

The source archive contains the script under `scripts/`. A wheel installation
contains it under `matlab_harness.bridge.toolkit_root()/scripts/`. Use the installed
environment's Python. Its `--help` lists the required arguments. Configure it
through the existing project-relative runtime JSON and `configure-runtime` command.

For example, run this configuration generator from an initialized project,
replacing the installation paths and model with your actual values:

```python
from pathlib import Path
import json
import sys
from matlab_harness.bridge import toolkit_root

base = [sys.executable, '-B',
        str(toolkit_root() / 'scripts' / 'codex_command_adapter.py'),
        '--prompt-file', '{prompt_file}', '--project', '{project}',
        '--schema-file', '{schema_file}', '--model', '{model}',
        '--reasoning-effort', 'medium',
        '--node', 'C:/your-node-install/node.exe',
        '--codex-js', 'C:/your-codex-install/bin/codex.js',
        '--codex-home', 'C:/your-existing-active-codex-home',
        '--evidence-root', 'C:/harness-evidence']
runtime = {'adapter': 'command', 'model': 'your-builder-model',
           'argv': base + ['--role', 'builder'],
           'roles': {role: {'argv': base + ['--role', role]}
                     for role in ('builder', 'reviewer', 'repair')}}
# Replace with an actually supported, independently verified reviewer identity.
runtime['roles']['reviewer']['model'] = 'your-verified-review-model'
Path('runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
```

Then execute `matlab-harness --project . configure-runtime --owner YOUR_OWNER --config
runtime.json`, inspect `next`, and start the [accounted journey](journey-runner.md).
The project owns role/native timeouts; invoke the script through that transport so
its actual child remains within the declared deadline. Each invocation creates a
new real CLI context. A successful transport can return an engineering rejection;
independent import, native checks and acceptance still apply.

This generator is a template: replace every installation path and the reviewer
model before execution. If the reviewer model you need is not available through the
CLI, use another runtime adapter or the manual packet/import path described in the
[runtime protocol](runtime-protocol.md). Do not switch reviewers after dispatch.

## Reviewer access

The default reviewer command uses Codex `--sandbox read-only`. If your Codex sandbox policy refuses file reads,
configure a supported access mode before retrying.
The optional reviewer arguments `--reviewer-access scope-guarded-native` use the
same native permissions as builders, then verify project contents before/after.
This requires that the operator permits native tool execution. It is an evidence
guard, not OS isolation. The script does not alter global host settings.

The guard refuses links/reparse points without traversing them and covers ordinary
project files and durable controls. It excludes root `.git` and the parent's active
`.matlab-harness/packets`. Restored-before-inspection changes, out-of-project writes and shared
MATLAB state are outside its proof. Direct reviewer simulation outputs and caches
to scratch outside the project; serialize shared MATLAB through the orchestrator.
The core additionally checks scoped-artifact freshness and actual contributor
independence.

## Identity, evidence and limits

The script keeps raw stdout/stderr, the final response, the exact argv, the source hash
and the matching local rollout. The observed model identity comes from that thread's
`turn_context`, never from the requested alias or an agent's claim. Missing or
ambiguous metadata, failed native execution, invalid structured output or changed
reviewer contents fail the transport. This is local client metadata, not server
authentication.

`--reasoning-effort medium` sets Codex's `model_reasoning_effort` for each role;
omit it to keep the CLI default. A mismatch between the requested and observed model
or effort fails the transport.

`--ignore-user-config` does not guarantee a clean profile or the absence of installed
skills or tools. The JSON Schema subset used by the harness is validated, and
unsupported constraints fail explicitly.

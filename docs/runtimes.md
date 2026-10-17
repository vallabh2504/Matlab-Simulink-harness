# Native runtimes and MATLAB bridge

The workflow is model agnostic. Configure builder and reviewer models in your host
runtime; the harness records the model IDs it actually observes. It never fakes
agent spawning or reviewer independence.

Built-in role adapters: `manual` (default: prompt packets you hand to any agent),
`agy` (Antigravity CLI), and `command` (any executable wrapper). The optional
[Codex CLI command adapter](codex-cli-adapter.md) is a ready-made `command` wrapper
for Codex. All of them accept your own installation paths and model names.

Codex can use project-local `.agents/skills`; Claude Code can use `.claude/skills`.
`install-skills` links the same canonical source into either location. Point the
agent at `adapters/workflow.md` and the selected `SKILL.md` files. For other
runtimes, load the shared instructions and use the CLI directly.

MATLAB bridge preference: use the available official MCP for interactive inspection
and native batch for clean reproducibility. The core also works without
MCP through its batch fallback. Configure the official server
according to [MathWorks' server repository](https://github.com/matlab/matlab-mcp-server).
Pass required Windows environment variables such as WINDIR in a restricted MCP host.
Consider its `--disable-telemetry` option; its documented default enables telemetry.
This package does not launch a shared multiuser licensed server or install global
toolkits. Inspect the current server's help/configuration before adding it.

Optional [MATLAB agentic toolkit](https://github.com/matlab/matlab-agentic-toolkit)
and [Simulink toolkit](https://github.com/matlab/simulink-agentic-toolkit) are upstream
resources, not bundled dependencies. The official
[installer](https://github.com/matlab/agentic-toolkit-installer) distinguishes MATLAB
R2021a+ and Simulink R2023a+ requirements.

Serialize shared MATLAB operations. Treat model load/update/compile/sim callbacks
as code execution; inspect trusted owned models only. Preserve user path and dirty
or running models. Distinct model names and isolated child processes help avoid
collisions. Native task workers should never use `clear all` or `bdclose all`.
Cancel/timeout is not proof a MATLAB child or external process tree has stopped;
inspect and stop owned processes before recovering resources.

# Hassle for VS Code

DESIGN.md §11, layer 2: commands (`Pull`/`Plan`/`Push`/`Validate`/`Test`/`Run`), Problems-pane
diagnostics from `hassle validate --json`, and a "Show Compiled YAML" panel from
`hassle explain --yaml`. Layer 1 (typed autocompletion via generated `.pyi` stubs) needs no
extension at all -- it's `hassle init`'s `.vscode/settings.json` + `hassle stubs`, working with
Pylance out of the box; see `packages/hassle-core/tests/test_registry_stubs_pyright*.py`.

**Not published to the Marketplace.** Install it from a local build.

## Private install

```sh
cd vscode-extension
npm install
npm run compile
npx vsce package         # produces hassle-vscode-<version>.vsix
code --install-extension hassle-vscode-<version>.vsix
```

(`vsce` itself is not a project dependency -- `npx` fetches it on demand; nothing here is
published anywhere.)

## Requirements

- A Hassle bundle open as the VS Code workspace root (a directory containing `hassle.toml`).
- The `hassle` CLI runnable from that root. By default the extension runs `uv run hassle`
  (matching `hassle init`'s own generated CI workflow) -- set `hassle.executablePath` if your
  bundle uses a different invocation (e.g. a globally `uv tool install`ed `hassle`, or a venv
  path).

## Settings

| Setting                    | Default | Meaning                                                                 |
|-----------------------------|---------|--------------------------------------------------------------------------|
| `hassle.executablePath`     | `""`    | Command used to invoke the CLI. Empty means `uv run hassle` from the workspace root. |

## Commands

| Command                     | CLI equivalent                    |
|------------------------------|------------------------------------|
| Hassle: Pull                 | `hassle pull`                     |
| Hassle: Plan                 | `hassle plan`                     |
| Hassle: Push                 | `hassle push`                     |
| Hassle: Validate              | `hassle validate` (+ `--json` for Problems-pane diagnostics) |
| Hassle: Test                 | `hassle test`                     |
| Hassle: Run (simulator)      | `hassle run <target>`             |
| Hassle: Show Compiled YAML   | `hassle explain <object_key> --yaml` |

## Development

```sh
npm install
npm run test:unit         # fast, no VS Code needed (mocked CLI subprocess)
npm run compile
npm run test:integration  # @vscode/test-electron, launches a real Extension Host
```

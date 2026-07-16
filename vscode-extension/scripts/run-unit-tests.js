#!/usr/bin/env node
/**
 * Cross-Node-version-safe wrapper for `npm run test:unit`
 * (CI's `.github/workflows/node.yml` pins Node 20 --
 * `--no-experimental-strip-types` was added in Node 22.6.0;
 * Node 20 exits immediately with "node: bad option: --no-experimental-
 * strip-types" (verified locally via `nvm use 20`), while omitting the flag
 * on Node >= 22.6 lets Node's own native TypeScript type-stripping (default
 * ON there) intercept `.ts` files before `ts-node/register` gets a chance,
 * failing on TS-only syntax (e.g. constructor parameter properties) that
 * "strip-only" mode rejects (`ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`, also
 * verified locally on Node 24/25). Hard-coding the flag broke one side or
 * the other depending on which Node happened to run it -- this script picks
 * it conditionally, at run time, from `process.versions.node` alone (never a
 * try/spawn-and-see: the two failure modes above are both "exits before
 * mocha loads a single test file", so there's nothing to detect from output).
 *
 * `--no-experimental-strip-types` only needs to be passed on a Node where
 * the underlying `--experimental-strip-types` family of flags exists at
 * all (>= 22.6.0); every earlier Node (this repo's CI-pinned 20 included)
 * has no such feature to opt out of, and passing the flag there is a hard
 * "bad option" exit, not a no-op.
 */
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

function supportsStripTypesFlag(nodeVersion) {
  const [major, minor] = nodeVersion.split(".").map(Number);
  return major > 22 || (major === 22 && minor >= 6);
}

const nodeArgs = [];
if (supportsStripTypesFlag(process.versions.node)) {
  nodeArgs.push("--no-experimental-strip-types");
}

const mochaBin = path.join(__dirname, "..", "node_modules", ".bin", "mocha");
const mochaArgs = [
  "--require",
  "ts-node/register",
  "--extension",
  "ts",
  "src/test/unit/**/*.test.ts",
];

const result = spawnSync(process.execPath, [...nodeArgs, mochaBin, ...mochaArgs], {
  stdio: "inherit",
  cwd: path.join(__dirname, ".."),
  // `**` glob expansion for the last mocha arg is normally the SHELL's job
  // (package.json's old inline script ran through `npm run`'s shell, which
  // expands globs before exec) -- `spawnSync` with an argv array does not
  // invoke a shell, so pass `shell: true` to keep that same glob-expansion
  // behavior here (mocha itself also accepts a literal glob string and
  // expands it internally as a fallback, but matching the previous
  // behavior exactly avoids any subtle difference in which files run).
  shell: true,
});

process.exit(result.status ?? 1);

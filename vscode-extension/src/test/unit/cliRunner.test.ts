import * as assert from "assert";
import {
  CliRunner,
  ProcessRunner,
  buildCandidates,
  buildInvocation,
  resolveBaseInvocation,
  CliInvocationError,
} from "../../cliRunner";

describe("cliRunner: CLI path resolution", () => {
  it("defaults to `uv run hassle` when hassle.executablePath is unset/empty", () => {
    assert.deepStrictEqual(resolveBaseInvocation(undefined), {
      command: "uv",
      baseArgs: ["run", "hassle"],
    });
    assert.deepStrictEqual(resolveBaseInvocation(""), {
      command: "uv",
      baseArgs: ["run", "hassle"],
    });
    assert.deepStrictEqual(resolveBaseInvocation("   "), {
      command: "uv",
      baseArgs: ["run", "hassle"],
    });
  });

  it("uses a configured executablePath as the literal command", () => {
    assert.deepStrictEqual(resolveBaseInvocation("/usr/local/bin/hassle"), {
      command: "/usr/local/bin/hassle",
      baseArgs: [],
    });
  });

  it("splits a multi-token executablePath (e.g. a custom uv invocation)", () => {
    assert.deepStrictEqual(resolveBaseInvocation("uv run --project /home/me/house hassle"), {
      command: "uv",
      baseArgs: ["run", "--project", "/home/me/house", "hassle"],
    });
  });
});

describe("cliRunner: invocation building", () => {
  it("always inserts --plain right after the base command, before the subcommand", () => {
    const invocation = buildInvocation("validate", ["--json"], undefined, true);
    assert.strictEqual(invocation.command, "uv");
    assert.deepStrictEqual(invocation.args, ["run", "hassle", "--plain", "validate", "--json"]);
  });

  it("builds a bare subcommand invocation with no extra args", () => {
    const invocation = buildInvocation("pull", [], "/opt/hassle", true);
    assert.strictEqual(invocation.command, "/opt/hassle");
    assert.deepStrictEqual(invocation.args, ["--plain", "pull"]);
  });

  it("passes through explain's object-key argument untouched", () => {
    const invocation = buildInvocation(
      "explain",
      ["automation:hall_light_on_motion", "--yaml"],
      undefined,
      true
    );
    assert.deepStrictEqual(invocation.args, [
      "run",
      "hassle",
      "--plain",
      "explain",
      "automation:hall_light_on_motion",
      "--yaml",
    ]);
  });
});

describe("cliRunner: fallback candidate chain", () => {
  it("an explicit hassle.executablePath setting wins outright -- no fallback candidates", () => {
    const candidates = buildCandidates("/custom/hassle", true);
    assert.strictEqual(candidates.length, 1);
    assert.strictEqual(candidates[0].command, "/custom/hassle");
    assert.deepStrictEqual(candidates[0].args, []);

    // Even with no pyproject.toml, an explicit setting is still the only candidate.
    const candidatesNoProject = buildCandidates("/custom/hassle", false);
    assert.strictEqual(candidatesNoProject.length, 1);
    assert.strictEqual(candidatesNoProject[0].command, "/custom/hassle");
  });

  it("no setting + pyproject.toml present -> `uv run hassle` first, bare `hassle` fallback", () => {
    const candidates = buildCandidates(undefined, true);
    assert.strictEqual(candidates.length, 2);
    assert.strictEqual(candidates[0].command, "uv");
    assert.deepStrictEqual(candidates[0].args, ["run", "hassle"]);
    assert.strictEqual(candidates[1].command, "hassle");
    assert.deepStrictEqual(candidates[1].args, []);
  });

  it("no setting + no pyproject.toml -> bare `hassle` from PATH only, no `uv run` attempt", () => {
    const candidates = buildCandidates(undefined, false);
    assert.strictEqual(candidates.length, 1);
    assert.strictEqual(candidates[0].command, "hassle");
    assert.deepStrictEqual(candidates[0].args, []);
  });

  it("empty/whitespace-only setting is treated the same as unset for fallback purposes", () => {
    assert.deepStrictEqual(buildCandidates("", true), buildCandidates(undefined, true));
    assert.deepStrictEqual(buildCandidates("   ", false), buildCandidates(undefined, false));
  });
});

class FakeProcessRunner implements ProcessRunner {
  public calls: { command: string; args: string[]; cwd: string }[] = [];
  constructor(private readonly result: { exitCode: number; stdout: string; stderr: string }) {}
  async run(command: string, args: string[], cwd: string) {
    this.calls.push({ command, args, cwd });
    return this.result;
  }
}

/** Simulates ENOENT-style spawn failures: rejects for any command in
 * `failingCommands`, otherwise delegates to a canned successful result. */
class SpawnFailureProcessRunner implements ProcessRunner {
  public calls: { command: string; args: string[]; cwd: string }[] = [];
  constructor(
    private readonly failingCommands: Set<string>,
    private readonly successResult: { exitCode: number; stdout: string; stderr: string } = {
      exitCode: 0,
      stdout: "ok",
      stderr: "",
    }
  ) {}
  async run(command: string, args: string[], cwd: string) {
    this.calls.push({ command, args, cwd });
    if (this.failingCommands.has(command)) {
      throw new Error(`spawn ${command} ENOENT`);
    }
    return this.successResult;
  }
}

/** Always rejects -- every candidate spawn-fails. */
class AlwaysFailingProcessRunner implements ProcessRunner {
  public calls: { command: string; args: string[]; cwd: string }[] = [];
  async run(command: string, args: string[], cwd: string): Promise<import("../../cliRunner").CliResult> {
    this.calls.push({ command, args, cwd });
    throw new Error(`spawn ${command} ENOENT`);
  }
}

describe("CliRunner: end-to-end argument recording (mocked subprocess)", () => {
  it("records the exact args each command invokes the CLI with", async () => {
    const fake = new FakeProcessRunner({ exitCode: 0, stdout: "{}", stderr: "" });
    const runner = new CliRunner(() => undefined, fake, () => true);

    await runner.run("validate", ["--json"], "/workspace/my-house");

    assert.strictEqual(fake.calls.length, 1);
    assert.strictEqual(fake.calls[0].command, "uv");
    assert.deepStrictEqual(fake.calls[0].args, ["run", "hassle", "--plain", "validate", "--json"]);
    assert.strictEqual(fake.calls[0].cwd, "/workspace/my-house");
  });

  it("respects a configured executablePath for every command", async () => {
    const fake = new FakeProcessRunner({ exitCode: 0, stdout: "", stderr: "" });
    const runner = new CliRunner(() => "/custom/hassle", fake, () => true);

    await runner.run("push", ["--yes"], "/workspace/my-house");

    assert.strictEqual(fake.calls[0].command, "/custom/hassle");
    assert.deepStrictEqual(fake.calls[0].args, ["--plain", "push", "--yes"]);
  });

  it("returns the mocked stdout/stderr/exitCode back to the caller", async () => {
    const fake = new FakeProcessRunner({ exitCode: 1, stdout: "out", stderr: "err" });
    const runner = new CliRunner(() => undefined, fake, () => true);

    const result = await runner.run("test", [], "/workspace/my-house");

    assert.strictEqual(result.exitCode, 1);
    assert.strictEqual(result.stdout, "out");
    assert.strictEqual(result.stderr, "err");
  });

  it("falls through to bare `hassle` when `uv run hassle` fails to spawn", async () => {
    const fake = new SpawnFailureProcessRunner(new Set(["uv"]), {
      exitCode: 0,
      stdout: "no changes",
      stderr: "",
    });
    const runner = new CliRunner(() => undefined, fake, () => true);

    const result = await runner.run("plan", [], "/workspace/my-house");

    assert.strictEqual(result.stdout, "no changes");
    assert.strictEqual(fake.calls.length, 2);
    assert.strictEqual(fake.calls[0].command, "uv");
    assert.strictEqual(fake.calls[1].command, "hassle");
    assert.deepStrictEqual(fake.calls[1].args, ["--plain", "plan"]);
  });

  it("does not fall through on a non-zero exit with real stderr -- that's a genuine CLI error, not a spawn failure", async () => {
    const fake = new FakeProcessRunner({ exitCode: 1, stdout: "", stderr: "bundle error: ..." });
    const runner = new CliRunner(() => undefined, fake, () => true);

    const result = await runner.run("validate", ["--json"], "/workspace/my-house");

    assert.strictEqual(fake.calls.length, 1, "must not try the fallback candidate after a real (non-spawn) failure");
    assert.strictEqual(result.exitCode, 1);
  });

  it("skips the `uv run hassle` candidate entirely when no pyproject.toml is present", async () => {
    const fake = new SpawnFailureProcessRunner(new Set(), { exitCode: 0, stdout: "ok", stderr: "" });
    const runner = new CliRunner(() => undefined, fake, () => false);

    await runner.run("plan", [], "/workspace/my-house");

    assert.strictEqual(fake.calls.length, 1);
    assert.strictEqual(fake.calls[0].command, "hassle");
  });

  it("throws a CliInvocationError listing every command tried with its exit code/stderr when all candidates spawn-fail", async () => {
    const fake = new AlwaysFailingProcessRunner();
    const runner = new CliRunner(() => undefined, fake, () => true);

    await assert.rejects(
      () => runner.run("plan", [], "/workspace/my-house"),
      (err: unknown) => {
        assert.ok(err instanceof CliInvocationError);
        const invocationErr = err as CliInvocationError;
        assert.strictEqual(invocationErr.attempts.length, 2);
        assert.strictEqual(invocationErr.attempts[0].candidate.command, "uv");
        assert.strictEqual(invocationErr.attempts[1].candidate.command, "hassle");
        assert.ok(invocationErr.attempts[0].error?.includes("ENOENT"));
        assert.ok(invocationErr.attempts[1].error?.includes("ENOENT"));
        assert.ok(invocationErr.message.includes("uv"));
        assert.ok(invocationErr.message.includes("hassle"));
        return true;
      }
    );
  });

  it("an explicit executablePath setting that fails to spawn produces a single-attempt CliInvocationError (no fallback)", async () => {
    const fake = new AlwaysFailingProcessRunner();
    const runner = new CliRunner(() => "/custom/hassle", fake, () => true);

    await assert.rejects(
      () => runner.run("plan", [], "/workspace/my-house"),
      (err: unknown) => {
        assert.ok(err instanceof CliInvocationError);
        const invocationErr = err as CliInvocationError;
        assert.strictEqual(invocationErr.attempts.length, 1);
        assert.strictEqual(invocationErr.attempts[0].candidate.command, "/custom/hassle");
        return true;
      }
    );
  });
});

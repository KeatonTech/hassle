import * as assert from "assert";
import { CliRunner, ProcessRunner, buildInvocation, resolveBaseInvocation } from "../../cliRunner";

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
    const invocation = buildInvocation("validate", ["--json"], undefined);
    assert.strictEqual(invocation.command, "uv");
    assert.deepStrictEqual(invocation.args, ["run", "hassle", "--plain", "validate", "--json"]);
  });

  it("builds a bare subcommand invocation with no extra args", () => {
    const invocation = buildInvocation("pull", [], "/opt/hassle");
    assert.strictEqual(invocation.command, "/opt/hassle");
    assert.deepStrictEqual(invocation.args, ["--plain", "pull"]);
  });

  it("passes through explain's object-key argument untouched", () => {
    const invocation = buildInvocation(
      "explain",
      ["automation:hall_light_on_motion", "--yaml"],
      undefined
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

class FakeProcessRunner implements ProcessRunner {
  public calls: { command: string; args: string[]; cwd: string }[] = [];
  constructor(private readonly result: { exitCode: number; stdout: string; stderr: string }) {}
  async run(command: string, args: string[], cwd: string) {
    this.calls.push({ command, args, cwd });
    return this.result;
  }
}

describe("CliRunner: end-to-end argument recording (mocked subprocess)", () => {
  it("records the exact args each command invokes the CLI with", async () => {
    const fake = new FakeProcessRunner({ exitCode: 0, stdout: "{}", stderr: "" });
    const runner = new CliRunner(() => undefined, fake);

    await runner.run("validate", ["--json"], "/workspace/my-house");

    assert.strictEqual(fake.calls.length, 1);
    assert.strictEqual(fake.calls[0].command, "uv");
    assert.deepStrictEqual(fake.calls[0].args, ["run", "hassle", "--plain", "validate", "--json"]);
    assert.strictEqual(fake.calls[0].cwd, "/workspace/my-house");
  });

  it("respects a configured executablePath for every command", async () => {
    const fake = new FakeProcessRunner({ exitCode: 0, stdout: "", stderr: "" });
    const runner = new CliRunner(() => "/custom/hassle", fake);

    await runner.run("push", ["--yes"], "/workspace/my-house");

    assert.strictEqual(fake.calls[0].command, "/custom/hassle");
    assert.deepStrictEqual(fake.calls[0].args, ["--plain", "push", "--yes"]);
  });

  it("returns the mocked stdout/stderr/exitCode back to the caller", async () => {
    const fake = new FakeProcessRunner({ exitCode: 1, stdout: "out", stderr: "err" });
    const runner = new CliRunner(() => undefined, fake);

    const result = await runner.run("test", [], "/workspace/my-house");

    assert.strictEqual(result.exitCode, 1);
    assert.strictEqual(result.stdout, "out");
    assert.strictEqual(result.stderr, "err");
  });
});

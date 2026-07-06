import * as vscode from "vscode";

/** Sync-state indicator (DESIGN §11 layer 2: "status bar sync state").
 * States mirror the CLI's own vocabulary (`hassle_cli.plan_render`'s plan
 * actions / `hassle status`'s output) rather than inventing a new one. */
export type SyncState = "unknown" | "checking" | "in-sync" | "pending-changes" | "error";

const LABELS: Record<SyncState, string> = {
  unknown: "$(question) Hassle",
  checking: "$(sync~spin) Hassle: checking...",
  "in-sync": "$(check) Hassle: in sync",
  "pending-changes": "$(warning) Hassle: changes pending",
  error: "$(error) Hassle: error",
};

export class HassleStatusBar {
  private readonly item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "hassle.plan";
    this.set("unknown");
  }

  set(state: SyncState): void {
    this.item.text = LABELS[state];
    this.item.show();
  }

  dispose(): void {
    this.item.dispose();
  }
}

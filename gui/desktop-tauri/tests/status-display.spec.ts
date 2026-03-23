import { expect, test } from "@playwright/test";

import {
  humanizeFailureReason,
  MEASUREMENT_STATE_LABELS,
  QA_GATE_STATUS_LABELS,
  renderOutcomeLabel,
  renderOutcomeTone,
  SAFE_RENDER_LIFECYCLE_LABELS,
} from "../src/status-display.ts";

test.describe("shared desktop status display mappings", () => {
  test("uses the shared result-bucket labels and tones", () => {
    expect(renderOutcomeLabel("valid_master")).toBe("Valid master render");
    expect(renderOutcomeLabel("diagnostics_only")).toBe("Invalid render with diagnostics");
    expect(renderOutcomeTone("partial_success")).toBe("warn");
    expect(renderOutcomeTone("full_failure")).toBe("danger");
  });

  test("uses the shared lifecycle, QA, and measurement labels", () => {
    expect(SAFE_RENDER_LIFECYCLE_LABELS.completed).toBe("Completed");
    expect(SAFE_RENDER_LIFECYCLE_LABELS.dry_run_only).toBe("Dry-run only");
    expect(QA_GATE_STATUS_LABELS.fail).toBe("Fail");
    expect(MEASUREMENT_STATE_LABELS.invalid_due_to_silence).toBe("Invalid due to silence");
  });

  test("humanizes known and fallback failure reasons consistently", () => {
    expect(humanizeFailureReason("RENDER_RESULT.NO_DECODABLE_STEMS")).toBe("No decodable stems");
    expect(humanizeFailureReason("ISSUE.RENDER.QA.SILENT_OUTPUT")).toBe("Silent Output");
  });
});

/**
 * MMO Tauri desktop GUI — screenshot capture spec.
 *
 * Generates PNGs for the User Manual. Each test navigates to a specific screen,
 * loads realistic fixture data where relevant, and writes a PNG to the output
 * directory.
 *
 * The committed manual baselines intentionally capture fixed, meaningful
 * desktop regions instead of full-document height. Each PNG is a stable
 * 1280 x 900 CSS-pixel viewport frame positioned around the canonical screen
 * or widget state for that manual section.
 *
 * These tests are skipped by default so they do not run during normal `npm test`
 * execution. Set MMO_CAPTURE_SCREENSHOTS=1 to enable them.
 *
 * Usage (dev server must be running, or the Playwright webServer block starts it):
 *
 *   MMO_CAPTURE_SCREENSHOTS=1 npx playwright test tests/capture-screenshots.spec.ts --project=firefox
 *
 * Or via the repo wrapper:
 *
 *   python tools/capture_tauri_screenshots.py
 *   python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
 *
 * Output files:
 *   tauri_session_ready.png   — Validate screen, session controls, empty state
 *   tauri_session_loaded_compact.png — Validate screen with loaded compact session shell
 *   tauri_scene_loaded.png    — Scene screen with objects, locks, and lint context
 *   tauri_scene_locks_editor.png — Scene screen with lock editor open
 *   tauri_results_loaded.png  — Results screen with receipt, QA, meters, confidence
 *   tauri_compare_loaded.png  — Compare screen with A/B data and loudness match
 *
 * Default output directory: docs/manual/assets/screenshots/ (repo root).
 * Override with MMO_SCREENSHOT_DIR=/abs/path.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, Page, test } from "@playwright/test";

type JsonObject = Record<string, unknown>;

type DesktopTestApi = {
  clearMockRpcResults?: () => void;
  setMockRpcResult?: (method: string, payload: JsonObject) => void;
};

// ---------------------------------------------------------------------------
// Output directory
// ---------------------------------------------------------------------------

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const OUT_DIR =
  process.env.MMO_SCREENSHOT_DIR ??
  path.join(REPO_ROOT, "docs", "manual", "assets", "screenshots");
const CANONICAL_VIEWPORT = { width: 1280, height: 900 } as const;
const CANONICAL_TOP_MARGIN_PX = 24;

function ensureOutDir(): void {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

function outPath(filename: string): string {
  return path.join(OUT_DIR, filename);
}

// ---------------------------------------------------------------------------
// Helpers shared with design-system.spec.ts
// ---------------------------------------------------------------------------

function jsonFile(
  name: string,
  payload: unknown,
): { buffer: Buffer; mimeType: string; name: string } {
  return {
    buffer: Buffer.from(JSON.stringify(payload, null, 2)),
    mimeType: "application/json",
    name,
  };
}

async function openScreen(page: Page, screen: string): Promise<void> {
  const label = screen.charAt(0).toUpperCase() + screen.slice(1);
  await page.getByRole("button", { name: label, exact: true }).click();
  await expect(page.locator(`#screen-${screen}`)).toBeVisible();
  await page.evaluate(() => {
    window.scrollTo(0, 0);
  });
}

async function settleLayout(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => resolve());
      });
    });
  });
}

async function setDetailsOpen(
  page: Page,
  selector: string,
  open: boolean,
): Promise<void> {
  const details = page.locator(selector);
  await expect(details).toBeVisible();
  const current = await details.evaluate((node) => (node as HTMLDetailsElement).open);
  if (current === open) {
    return;
  }
  await details.locator("summary").click();
  await expect
    .poll(async () => details.evaluate((node) => (node as HTMLDetailsElement).open))
    .toBe(open);
}

type CanonicalCaptureOptions = {
  anchorSelector: string;
  viewportSelectors: string[];
};

async function captureCanonicalViewport(
  page: Page,
  filename: string,
  options: CanonicalCaptureOptions,
): Promise<void> {
  const anchor = page.locator(options.anchorSelector);
  await expect(page.locator("#app-shell")).toBeVisible();
  await expect(anchor).toBeVisible();

  await page.evaluate(
    ({ selector, marginTop }) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) {
        throw new Error(`Missing canonical screenshot anchor: ${selector}`);
      }
      element.scrollIntoView({ block: "start", inline: "nearest" });
      if (marginTop > 0) {
        window.scrollBy(0, -marginTop);
      }
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    },
    { selector: options.anchorSelector, marginTop: CANONICAL_TOP_MARGIN_PX },
  );

  await settleLayout(page);

  for (const selector of options.viewportSelectors) {
    await expect(page.locator(selector)).toBeInViewport();
  }

  await page.screenshot({
    path: outPath(filename),
    fullPage: false,
    animations: "disabled",
    caret: "hide",
    scale: "css",
  });
}

const SESSION_FIXTURE = {
  sceneLocksPath: "/tmp/mmo-workspace/project/scene_locks.yaml",
  stemsDir: "/tmp/mmo-stems",
  workspaceDir: "/tmp/mmo-workspace",
};

const SCENE_JSON_FIXTURE = {
  intent: {
    confidence: 0.74,
    perspective: "in_orchestra",
    locks: ["LOCK.PRESERVE_DYNAMICS"],
  },
  objects: [
    {
      object_id: "OBJ.VOX",
      label: "Vox",
      role_id: "ROLE.VOCAL.LEAD",
      group_bus: "BUS.VOX",
      intent: {
        confidence: 0.91,
        width: 0.4,
        depth: 0.5,
        locks: ["LOCK.NO_STEREO_WIDENING"],
        position: { azimuth_deg: 0 },
      },
    },
    {
      object_id: "OBJ.GTR",
      label: "Guitar",
      role_id: "ROLE.GTR.ELECTRIC",
      group_bus: "BUS.MUSIC",
      intent: {
        confidence: 0.66,
        width: 0.3,
        depth: 0.42,
        locks: [],
        position: { azimuth_deg: 24 },
      },
    },
  ],
  beds: [
    {
      bed_id: "BED.BUS.MUSIC",
      bus_id: "BUS.MUSIC",
      label: "Music Bed",
      kind: "bed",
      width_hint: 0.85,
      intent: {
        confidence: 0.82,
        diffuse: 0.85,
        locks: [],
      },
    },
  ],
};

const SCENE_LINT_FIXTURE = {
  summary: { error_count: 1, warn_count: 2 },
  issues: [
    {
      severity: "warn",
      issue_id: "ISSUE.SCENE_LINT.IMMERSIVE_LOW_CONFIDENCE",
      path: "intent.confidence",
      message:
        "Immersive perspective is requested with low scene confidence.",
    },
  ],
};

const SCENE_LOCKS_INSPECT_FIXTURE = {
  objects: [
    {
      confidence: 0.91,
      inferred_role_id: "ROLE.VOCAL.LEAD",
      label: "Vox",
      object_id: "OBJ.VOX",
      role_override_id: "",
      stem_id: "STEM.VOX",
    },
    {
      confidence: 0.66,
      front_only_override: true,
      inferred_role_id: "ROLE.GTR.ELECTRIC",
      label: "Guitar",
      object_id: "OBJ.GTR",
      role_override_id: "ROLE.GTR.ELECTRIC",
      stem_id: "STEM.GTR",
      surround_cap_override: 0,
    },
  ],
  overrides_count: 1,
  perspective: "in_orchestra",
  perspective_values: ["audience", "in_orchestra"],
  role_options: [
    { label: "Lead Vocal", role_id: "ROLE.VOCAL.LEAD" },
    { label: "Electric Guitar", role_id: "ROLE.GTR.ELECTRIC" },
  ],
  scene_locks_path: "/tmp/mmo-workspace/project/scene_locks.yaml",
  scene_path: "/tmp/mmo-workspace/project/drafts/scene.draft.json",
};

async function fillCommittedTextInput(
  page: Page,
  selector: string,
  value: string,
): Promise<void> {
  const locator = page.locator(selector);
  await locator.fill(value);
  await locator.dispatchEvent("input");
  await locator.dispatchEvent("change");
}

async function loadCompactWorkspaceShell(page: Page): Promise<void> {
  await fillCommittedTextInput(page, "#stems-dir-input", SESSION_FIXTURE.stemsDir);
  await fillCommittedTextInput(page, "#workspace-dir-input", SESSION_FIXTURE.workspaceDir);
  await fillCommittedTextInput(page, "#scene-locks-input", SESSION_FIXTURE.sceneLocksPath);
  await expect(page.locator("#app-shell")).toHaveAttribute("data-workspace-mode", "compact");
}

async function setDesktopRpcMock(
  page: Page,
  method: string,
  payload: JsonObject,
): Promise<void> {
  await page.waitForFunction(() => Boolean((window as { __MMO_DESKTOP_TEST__?: DesktopTestApi }).__MMO_DESKTOP_TEST__));
  await page.evaluate(
    ({ method, payload }) => {
      (window as { __MMO_DESKTOP_TEST__?: DesktopTestApi }).__MMO_DESKTOP_TEST__?.setMockRpcResult?.(method, payload);
    },
    { method, payload },
  );
}

async function loadSceneWorkspace(page: Page): Promise<void> {
  await fillCommittedTextInput(page, "#workspace-dir-input", SESSION_FIXTURE.workspaceDir);
  await page.locator("#scene-json-file-input").setInputFiles(
    jsonFile("scene.json", SCENE_JSON_FIXTURE),
  );
  await page.locator("#scene-lint-file-input").setInputFiles(
    jsonFile("scene_lint.json", SCENE_LINT_FIXTURE),
  );
  await expect(page.locator("#scene-summary-text")).toContainText("Perspective:");
}

async function ensureSceneLockEditorOpen(page: Page): Promise<void> {
  const details = page.locator("#scene-locks-editor-details");
  const open = await details.evaluate((node) => (node as HTMLDetailsElement).open);
  if (!open) {
    await page.locator("#scene-locks-editor-details summary").click();
  }
}

// ---------------------------------------------------------------------------
// Capture suite — skipped unless MMO_CAPTURE_SCREENSHOTS=1
// ---------------------------------------------------------------------------

test.describe("MMO Tauri screenshot capture", () => {
  test.skip(
    !process.env.MMO_CAPTURE_SCREENSHOTS,
    "Set MMO_CAPTURE_SCREENSHOTS=1 to run screenshot capture",
  );

  test.use({ viewport: CANONICAL_VIEWPORT });

  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  // -------------------------------------------------------------------------
  // 1. Validate screen — session ready, empty state
  // -------------------------------------------------------------------------
  test("capture: validate screen (session ready)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "validate");
    await captureCanonicalViewport(page, "tauri_session_ready.png", {
      anchorSelector: "#app-shell",
      viewportSelectors: [
        "#screen-validate",
        "#workflow-validate-button",
        "#validate-summary-text",
      ],
    });
  });

  // -------------------------------------------------------------------------
  // 2. Validate screen — loaded workspace compacts the shared shell
  // -------------------------------------------------------------------------
  test("capture: validate screen (loaded compact session shell)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "validate");
    await loadCompactWorkspaceShell(page);
    await captureCanonicalViewport(page, "tauri_session_loaded_compact.png", {
      anchorSelector: "#app-shell",
      viewportSelectors: [
        "#screen-validate",
        "#workflow-validate-button",
        "#validate-summary-text",
      ],
    });
  });

  // -------------------------------------------------------------------------
  // 3. Scene screen — objects, locks, and lint context loaded
  // -------------------------------------------------------------------------
  test("capture: scene screen (loaded)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "scene");
    await loadSceneWorkspace(page);
    await setDetailsOpen(page, "#scene-locks-editor-details", false);
    await setDesktopRpcMock(page, "scene.locks.inspect", SCENE_LOCKS_INSPECT_FIXTURE);
    await page.locator("#scene-locks-inspect-button").click();
    await expect(page.locator("#scene-lock-summary-rows")).toContainText("2 row(s)");
    await expect(page.locator("#scene-lock-summary-path")).toContainText("scene_locks.yaml");
    await captureCanonicalViewport(page, "tauri_scene_loaded.png", {
      anchorSelector: "[data-widget-id=\"widget.scene.locks\"]",
      viewportSelectors: [
        "#scene-locks-inspect-button",
        "#scene-lock-summary-rows",
        "#scene-lock-summary-path",
      ],
    });
  });

  // -------------------------------------------------------------------------
  // 4. Scene screen — lock editor open through inspect flow
  // -------------------------------------------------------------------------
  test("capture: scene screen (lock editor open)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "scene");
    await loadSceneWorkspace(page);
    await ensureSceneLockEditorOpen(page);
    await setDesktopRpcMock(page, "scene.locks.inspect", SCENE_LOCKS_INSPECT_FIXTURE);
    await page.locator("#scene-locks-inspect-button").click();
    await expect(page.locator("#scene-locks-editor")).toContainText("Front-only");
    await page.locator("#scene-locks-perspective-select").selectOption("audience");
    await expect(page.locator("#scene-lock-summary-dirty")).toContainText("Yes");
    await captureCanonicalViewport(page, "tauri_scene_locks_editor.png", {
      anchorSelector: "[data-widget-id=\"widget.scene.locks\"]",
      viewportSelectors: [
        "#scene-locks-editor-details",
        "#scene-locks-editor",
        "#scene-lock-summary-dirty",
      ],
    });
  });

  // -------------------------------------------------------------------------
  // 5. Results screen — receipt, manifest, QA loaded
  // -------------------------------------------------------------------------
  test("capture: results screen (loaded)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "results");

    await page.locator("#results-receipt-file-input").setInputFiles(
      jsonFile("safe_render_receipt.json", {
        status: "completed",
        recommendations_summary: {
          total: 2,
          eligible: 2,
          auto_eligible: 2,
          approved_by_user: 0,
          blocked: 1,
          applied: 1,
        },
        eligible_recommendations: [
          {
            recommendation_id: "REC.RENDER.003",
            action_id: "ACTION.SPATIAL.NARROW",
            scope: { bus_id: "BUS.MUSIC" },
            deltas: [
              {
                param_id: "PARAM.STEREO.WIDTH",
                from: 1.0,
                to: 0.85,
                unit: "ratio",
                confidence: 0.58,
                evidence_ref: "EVID.SIDE.001",
              },
            ],
            gate_summary: "eligible",
          },
        ],
        applied_recommendations: [
          {
            recommendation_id: "REC.RENDER.001",
            action_id: "ACTION.UTILITY.GAIN",
            scope: { stem_id: "STEM.VOX" },
            deltas: [
              {
                param_id: "PARAM.UTILITY.GAIN_DB",
                from: 0.0,
                to: -2.4,
                unit: "dB",
                confidence: 0.82,
                evidence_ref: "EVID.GAIN.001",
              },
              {
                param_id: "PARAM.DYNAMICS.THRESHOLD_DB",
                from: -18.0,
                to: -20.5,
                unit: "dB",
                confidence: 0.79,
                evidence_ref: "EVID.DYN.002",
              },
            ],
            gate_summary: "applied",
            notes: "Trimmed the lead for extra headroom.",
          },
        ],
        blocked_recommendations: [
          {
            recommendation_id: "REC.RENDER.002",
            gate_summary: "blocked_by_gates",
            action_id: "ACTION.STEREO.WIDEN",
            scope: { bus_id: "BUS.MUSIC" },
            deltas: [
              {
                param_id: "PARAM.STEREO.WIDTH",
                from: 1.0,
                to: 1.2,
                unit: "ratio",
                confidence: 0.41,
                evidence_ref: "EVID.WIDTH.004",
              },
            ],
          },
        ],
        qa_issues: [],
      }),
    );

    await page.locator("#results-manifest-file-input").setInputFiles(
      jsonFile("render_manifest.json", {
        renderer_manifests: [
          {
            renderer_id: "PLUGIN.RENDERER.SAFE",
            outputs: [
              {
                output_id: "OUT.001",
                file_path: "render/2_0/mix.wav",
                format: "wav",
                layout_id: "LAYOUT.2_0",
                recommendation_id: "REC.RENDER.001",
              },
            ],
            skipped: [],
          },
        ],
      }),
    );

    await page.locator("#results-qa-file-input").setInputFiles(
      jsonFile("render_qa.json", {
        thresholds: {
          correlation_warn_lte: -0.2,
          polarity_error_correlation_lte: -0.6,
        },
        jobs: [
          {
            job_id: "JOB.001",
            input: {
              metrics: {
                rms_dbfs: -8.0,
                peak_dbfs: -1.0,
              },
            },
            outputs: [
              {
                path: "render/2_0/mix.wav",
                metrics: {
                  integrated_lufs: -14.1,
                  rms_dbfs: -10.2,
                  crest_factor_db: 9.4,
                  correlation_lr: 0.14,
                  side_mid_ratio_db: -2.8,
                },
              },
            ],
            comparisons: [
              {
                metrics_delta: {
                  rms_dbfs: -2.4,
                  peak_dbfs: -1.1,
                  correlation_lr: -0.12,
                  side_mid_ratio_db: -0.6,
                },
              },
            ],
          },
        ],
        issues: [
          {
            severity: "warn",
            issue_id: "ISSUE.RENDER.QA.TRUE_PEAK_WARN",
            output_path: "render/2_0/mix.wav",
            message: "True peak is close to threshold.",
          },
        ],
      }),
    );

    await expect(page.locator("#results-readout-primary")).toContainText(
      "completed",
    );
    await captureCanonicalViewport(page, "tauri_results_loaded.png", {
      anchorSelector: "[data-widget-id=\"widget.results.summary\"]",
      viewportSelectors: [
        "#results-readout-primary",
        "#results-change-summary",
        "#results-what-changed-text",
      ],
    });
  });

  // -------------------------------------------------------------------------
  // 6. Compare screen — A/B loaded, loudness match active
  // -------------------------------------------------------------------------
  test("capture: compare screen (loaded)", async ({ page }) => {
    ensureOutDir();
    await openScreen(page, "compare");
    await fillCommittedTextInput(page, "#compare-a-input", "/tmp/variant_a");
    await fillCommittedTextInput(page, "#compare-b-input", "/tmp/variant_b");

    await page.locator("#compare-report-file-input").setInputFiles(
      jsonFile("compare_report.json", {
        a: {
          label: "variant_a",
          profile_id: "PROFILE.ASSIST",
          preset_id: "PRESET.SAFE",
        },
        b: {
          label: "variant_b",
          profile_id: "PROFILE.FULL_SEND",
          preset_id: "PRESET.WIDE",
        },
        diffs: {
          profile_id: {
            a: "PROFILE.ASSIST",
            b: "PROFILE.FULL_SEND",
          },
          preset_id: {
            a: "PRESET.SAFE",
            b: "PRESET.WIDE",
          },
          meters: {
            a: "METER.SAFE",
            b: "METER.WIDE",
          },
          output_formats: {
            a: ["wav"],
            b: ["wav"],
          },
          metrics: {
            downmix_qa: {
              lufs_delta: { a: -14.0, b: -15.2, delta: -1.2 },
              true_peak_delta: { a: -1.0, b: -0.7, delta: 0.3 },
              corr_delta: { a: 0.34, b: 0.18, delta: -0.16 },
            },
            mix_complexity: null,
            change_flags: {
              extreme_count: { a: 0, b: 0, delta: 0 },
              translation_risk: { a: "low", b: "medium", shift: 1 },
            },
          },
        },
        notes: [
          "Profile changed: PROFILE.ASSIST -> PROFILE.FULL_SEND.",
          "Translation risk moved upward: low -> medium.",
        ],
        warnings: [
          "Translation risk increased from A to B; verify on small speakers before choosing.",
        ],
        loudness_match: {
          status: "matched",
          enabled_by_default: true,
          evaluation_only: true,
          compensated_side: "b",
          method_id:
            "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_INTEGRATED_LUFS",
          measurement_unit_id: "UNIT.LUFS",
          measurement_a: -14.0,
          measurement_b: -15.2,
          compensation_db: 1.2,
          source_artifacts: {
            a_render_qa_path: "/tmp/variant_a/render_qa.json",
            b_render_qa_path: "/tmp/variant_b/render_qa.json",
          },
          details:
            "Default fair-listen applies +1.2 dB to B using render_qa mean integrated LUFS (A=-14, B=-15.2).",
        },
      }),
    );

    await page.locator("#compare-a-qa-file-input").setInputFiles(
      jsonFile("a.render_qa.json", {
        jobs: [
          {
            job_id: "JOB.001",
            outputs: [
              {
                path: "variant_a/mix.wav",
                metrics: { integrated_lufs: -14.0, rms_dbfs: -10.0 },
              },
            ],
          },
        ],
      }),
    );

    await page.locator("#compare-b-qa-file-input").setInputFiles(
      jsonFile("b.render_qa.json", {
        jobs: [
          {
            job_id: "JOB.001",
            outputs: [
              {
                path: "variant_b/mix.wav",
                metrics: { integrated_lufs: -15.2, rms_dbfs: -11.0 },
              },
            ],
          },
        ],
      }),
    );

    await expect(page.locator("#ab-compensation")).toContainText(
      "Fair listen on",
    );
    await captureCanonicalViewport(page, "tauri_compare_loaded.png", {
      anchorSelector: "#screen-compare",
      viewportSelectors: [
        "#compare-a-input",
        "#ab-compensation",
        "#compare-readout-primary",
      ],
    });
  });
});

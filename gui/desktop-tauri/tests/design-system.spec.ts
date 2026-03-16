import { expect, test } from "@playwright/test";

type ScreenKey = "validate" | "analyze" | "scene" | "render" | "results" | "compare";

type WidgetBox = {
  bottom: number;
  height: number;
  right: number;
  widgetId: string;
  width: number;
  x: number;
  y: number;
};

type DesktopTestApi = {
  setMockRpcResult?: (method: string, payload: Record<string, unknown>) => void;
};

const screens: Record<ScreenKey, { buttonLabel: string; requiredWidgets: string[] }> = {
  analyze: {
    buttonLabel: "Analyze",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.analyze.actions",
      "widget.analyze.summary",
      "widget.analyze.scan",
      "widget.analyze.json",
    ],
  },
  compare: {
    buttonLabel: "Compare",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.compare.inputs",
      "widget.compare.summary",
      "widget.compare.inspection",
    ],
  },
  render: {
    buttonLabel: "Render",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.render.actions",
      "widget.render.status",
      "widget.render.progress",
      "widget.render.output",
    ],
  },
  results: {
    buttonLabel: "Results",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.results.browser",
      "widget.results.summary",
      "widget.results.what_changed",
      "widget.results.preview",
      "widget.results.inspection",
    ],
  },
  scene: {
    buttonLabel: "Scene",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.scene.actions",
      "widget.scene.summary",
      "widget.scene.xy_focus",
      "widget.scene.objects",
      "widget.scene.locks",
      "widget.scene.json",
    ],
  },
  validate: {
    buttonLabel: "Validate",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.validate.actions",
      "widget.validate.summary",
      "widget.validate.artifacts",
      "widget.validate.json",
    ],
  },
};

const viewports = [
  { label: "mobile", width: 390, height: 844 },
  { label: "laptop", width: 1280, height: 900 },
  { label: "desktop", width: 1728, height: 1117 },
];

function overlaps(left: WidgetBox, right: WidgetBox): boolean {
  const gutter = 1;
  return (
    left.x < (right.right - gutter) &&
    (left.right - gutter) > right.x &&
    left.y < (right.bottom - gutter) &&
    (left.bottom - gutter) > right.y
  );
}

async function openScreen(page: Parameters<typeof test>[0]["page"], screen: ScreenKey): Promise<void> {
  await page.getByRole("button", { name: screens[screen].buttonLabel, exact: true }).click();
  await expect(page.locator(`#screen-${screen}`)).toBeVisible();
  await page.evaluate(() => {
    window.scrollTo(0, 0);
  });
}

async function visibleWidgetBoxes(page: Parameters<typeof test>[0]["page"]): Promise<WidgetBox[]> {
  return await page.locator("[data-widget-id]").evaluateAll((nodes) => {
    return nodes.flatMap((node) => {
      if (!(node instanceof HTMLElement)) {
        return [];
      }
      const style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || node.hidden) {
        return [];
      }
      const rect = node.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) {
        return [];
      }
      return [{
        widgetId: node.dataset.widgetId ?? "",
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        right: rect.right,
        bottom: rect.bottom,
      }];
    });
  });
}

function jsonFile(name: string, payload: unknown): { buffer: Buffer; mimeType: string; name: string } {
  return {
    buffer: Buffer.from(JSON.stringify(payload, null, 2)),
    mimeType: "application/json",
    name,
  };
}

test.describe("desktop workflow design system", () => {
  for (const viewport of viewports) {
    test(`widgets stay on-screen without overlaps at ${viewport.label}`, async ({ page }) => {
      test.slow();
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");

      for (const screen of Object.keys(screens) as ScreenKey[]) {
        await openScreen(page, screen);
        const boxes = await visibleWidgetBoxes(page);
        const boxIds = new Set(boxes.map((box) => box.widgetId));

        for (const requiredWidget of screens[screen].requiredWidgets) {
          expect(boxIds.has(requiredWidget)).toBeTruthy();
          const locator = page.locator(`[data-widget-id="${requiredWidget}"]`);
          await locator.scrollIntoViewIfNeeded();
          const widgetBox = await locator.boundingBox();
          expect(widgetBox).not.toBeNull();
          if (widgetBox === null) {
            continue;
          }
          expect(widgetBox.x).toBeGreaterThanOrEqual(0);
          expect(widgetBox.y).toBeGreaterThanOrEqual(0);
          expect(widgetBox.x + widgetBox.width).toBeLessThanOrEqual(viewport.width);
          expect(widgetBox.y + widgetBox.height).toBeLessThanOrEqual(viewport.height);
        }

        for (let index = 0; index < boxes.length; index += 1) {
          for (let otherIndex = index + 1; otherIndex < boxes.length; otherIndex += 1) {
            expect(overlaps(boxes[index] as WidgetBox, boxes[otherIndex] as WidgetBox)).toBeFalsy();
          }
        }
      }
    });
  }

  test("numeric controls expose units and exact entry fields", async ({ page }) => {
    await page.goto("/");
    const cases: Array<{ screen: ScreenKey; selector: string }> = [
      { screen: "scene", selector: '[data-widget-id="widget.scene.xy_focus"]' },
      { screen: "results", selector: '[data-widget-id="widget.results.summary"]' },
      { screen: "compare", selector: '[data-widget-id="widget.compare.inspection"]' },
    ];

    for (const { screen, selector } of cases) {
      await openScreen(page, screen);
      const widget = page.locator(selector);
      await expect(widget.locator(".control-unit").first()).toBeVisible();
      await expect(widget.locator('input[type="number"]').first()).toBeVisible();
    }
  });

  test("global scale control and fine adjust modifier feedback are active", async ({ page }) => {
    await page.goto("/");
    await openScreen(page, "results");

    await page.getByRole("button", { name: "115%", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-gui-scale", "comfort");
    const scale = await page.locator("html").evaluate((element) => {
      return window.getComputedStyle(element).getPropertyValue("--gui-scale").trim();
    });
    expect(scale).toBe("1.15");

    const sliderInput = page.locator("#results-detail-input");
    await sliderInput.fill("6");
    await sliderInput.press("Tab");

    await page.keyboard.down("Shift");
    await expect(page.locator("#fine-adjust-indicator")).toContainText("Fine adjust active");
    await page.keyboard.up("Shift");
    await expect(page.locator("#results-detail-value")).toContainText("6 line(s) of detail");
  });

  test("loaded workspace mode compacts the left rail after a workspace is chosen", async ({ page }) => {
    await page.setViewportSize({ width: 1728, height: 1117 });
    await page.goto("/");

    const shell = page.locator("#app-shell");
    const hero = page.locator('[data-section-id="header"]');
    await expect(shell).toHaveAttribute("data-workspace-mode", "hero");
    const emptyWidth = await hero.evaluate((element) => element.getBoundingClientRect().width);

    await page.locator("#workspace-dir-input").fill("/tmp/mmo-workspace");
    await page.locator("#workspace-dir-input").dispatchEvent("input");
    await page.locator("#workspace-dir-input").dispatchEvent("change");

    await expect(shell).toHaveAttribute("data-workspace-mode", "compact");
    const loadedWidth = await hero.evaluate((element) => element.getBoundingClientRect().width);
    expect(loadedWidth).toBeLessThan(emptyWidth);
  });

  test("session and compare recents persist in the desktop-safe fallback store", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("#stems-dir-browse-button")).toBeVisible();
    await expect(page.locator("#workspace-dir-browse-button")).toBeVisible();
    await openScreen(page, "compare");
    await expect(page.locator("#compare-a-file-browse-button")).toBeVisible();
    await expect(page.locator("#compare-b-folder-browse-button")).toBeVisible();

    await page.locator("#stems-dir-input").fill("/tmp/stems-a");
    await page.locator("#stems-dir-input").dispatchEvent("change");
    await page.locator("#workspace-dir-input").fill("/tmp/workspace-a");
    await page.locator("#workspace-dir-input").dispatchEvent("change");
    await page.locator("#scene-locks-input").fill("/tmp/workspace-a/project/scene_locks.yaml");
    await page.locator("#scene-locks-input").dispatchEvent("change");

    await page.locator("#compare-a-input").fill("/tmp/render-a");
    await page.locator("#compare-a-input").dispatchEvent("change");
    await page.locator("#compare-b-input").fill("/tmp/render-b");
    await page.locator("#compare-b-input").dispatchEvent("change");

    await expect(page.locator("#recent-stems-dir-list")).toContainText("/tmp/stems-a");
    await expect(page.locator("#recent-workspace-dir-list")).toContainText("/tmp/workspace-a");
    await expect(page.locator("#recent-scene-locks-list")).toContainText("scene_locks.yaml");
    await expect(page.locator("#recent-compare-a-list")).toContainText("/tmp/render-a");
    await expect(page.locator("#recent-compare-b-list")).toContainText("/tmp/render-b");

    await page.reload();

    await expect(page.locator("#recent-stems-dir-list")).toContainText("/tmp/stems-a");
    await expect(page.locator("#recent-workspace-dir-list")).toContainText("/tmp/workspace-a");
    await openScreen(page, "compare");
    await expect(page.locator("#recent-compare-a-list")).toContainText("/tmp/render-a");
    await expect(page.locator("#recent-compare-b-list")).toContainText("/tmp/render-b");
  });

  test("scene screen shows generated scene summary plus lint and lock context", async ({ page }) => {
    await page.goto("/");
    await openScreen(page, "scene");
    await page.locator("#workspace-dir-input").fill("/tmp/mmo-workspace");

    await page.locator("#scene-json-file-input").setInputFiles(jsonFile("scene.json", {
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
    }));
    await page.locator("#scene-lint-file-input").setInputFiles(jsonFile("scene_lint.json", {
      summary: { error_count: 1, warn_count: 2 },
      issues: [
        {
          severity: "warn",
          issue_id: "ISSUE.SCENE_LINT.IMMERSIVE_LOW_CONFIDENCE",
          path: "intent.confidence",
          message: "Immersive perspective is requested with low scene confidence.",
        },
      ],
    }));
    await page.evaluate((payload) => {
      (window as typeof window & {
        __MMO_DESKTOP_TEST__?: DesktopTestApi;
      }).__MMO_DESKTOP_TEST__?.setMockRpcResult?.("scene.locks.inspect", payload);
    }, {
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
      scene_locks_path: "/tmp/project/scene_locks.yaml",
      scene_path: "/tmp/project/drafts/scene.draft.json",
    });
    await page.locator("#scene-locks-editor-details summary").click();
    await page.locator("#scene-locks-inspect-button").click();

    await expect(page.locator("#scene-summary-text")).toContainText("Perspective:");
    await expect(page.locator("#scene-summary-text")).toContainText("OBJ.VOX");
    await expect(page.locator("#scene-locks-text")).toContainText("LOCK.PRESERVE_DYNAMICS");
    await expect(page.locator("#scene-lock-summary-perspective")).toContainText("in_orchestra");
    await expect(page.locator("#scene-lock-summary-rows")).toContainText("2 row(s)");
    await expect(page.locator("#scene-lock-summary-path")).toContainText("scene_locks.yaml");
    await expect(page.locator("#scene-locks-editor")).toContainText("Front-only");
    await expect(page.locator("#scene-focus-caption")).toContainText("Nearest:");

    await page.locator("#scene-locks-perspective-select").selectOption("audience");
    await expect(page.locator("#scene-lock-summary-dirty")).toContainText("Yes");
  });

  test("results screen is artifact-driven and ties changes back to output paths", async ({ page }) => {
    await page.goto("/");
    await openScreen(page, "results");

    await page.locator("#results-receipt-file-input").setInputFiles(jsonFile("safe_render_receipt.json", {
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
    }));
    await page.locator("#results-manifest-file-input").setInputFiles(jsonFile("render_manifest.json", {
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
    }));
    await page.locator("#results-qa-file-input").setInputFiles(jsonFile("render_qa.json", {
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
    }));

    await expect(page.locator("#results-readout-primary")).toContainText("completed");
    await expect(page.locator("#results-change-summary")).toContainText("Applied 1");
    await expect(page.locator("#results-what-changed-text")).toContainText("render/2_0/mix.wav");
    await expect(page.locator("#results-qa-text")).toContainText("ISSUE.RENDER.QA.TRUE_PEAK_WARN");
    await expect(page.locator("#artifact-browser-list")).toContainText("render/2_0/mix.wav");
    await expect(page.locator("#results-confidence-list")).toContainText("REC.RENDER.001");
    await expect(page.locator("#results-confidence-list")).toContainText("81% High");
    await expect(page.locator("#results-gain-reduction-value")).toContainText("2.4 dB");
    await expect(page.locator("#results-phase-correlation-value")).toContainText("0.14 corr");
    await expect(page.locator("#results-transfer-note")).toContainText("threshold=-20.5 dB");
    await expect(page.locator("#results-vectorscope-summary")).toContainText("side/mid=-2.8 dB");
    await expect(page.locator("#results-summary-actions")).toContainText("Open receipt");
    await expect(page.locator("#results-qa-actions")).toContainText("Open QA");

    await page.getByRole("button", { name: /render\/2_0\/mix\.wav/i }).click();
    await expect(page.locator("#artifact-preview-actions")).toContainText("Copy path");
    await expect(page.locator("#artifact-preview-actions")).toContainText("Reveal");
    await expect(page.locator("#artifact-preview-actions")).toContainText("Compare");

    await page.locator("#results-qa-actions").getByRole("button", { name: "Open QA" }).click();
    await expect(page.locator("#artifact-preview-name")).toContainText("Render QA");

    await page.getByText("Dynamics and stereo inspection", { exact: true }).click();
    await page.locator("#results-phase-hint-trigger").focus();
    await expect(page.locator("#hint-results-phase")).toBeVisible();
    await expect(page.locator("#hint-results-phase")).toContainText("Why:");
  });

  test("compare screen uses compare artifact plus A/B render QA for loudness match", async ({ page }) => {
    await page.goto("/");
    await openScreen(page, "compare");

    await page.locator("#compare-report-file-input").setInputFiles(jsonFile("compare_report.json", {
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
            lufs_delta: {
              a: -14.0,
              b: -15.2,
              delta: -1.2,
            },
            true_peak_delta: {
              a: -1.0,
              b: -0.7,
              delta: 0.3,
            },
            corr_delta: {
              a: 0.34,
              b: 0.18,
              delta: -0.16,
            },
          },
          mix_complexity: null,
          change_flags: {
            extreme_count: {
              a: 0,
              b: 0,
              delta: 0,
            },
            translation_risk: {
              a: "low",
              b: "medium",
              shift: 1,
            },
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
        method_id: "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_INTEGRATED_LUFS",
        measurement_unit_id: "UNIT.LUFS",
        measurement_a: -14.0,
        measurement_b: -15.2,
        compensation_db: 1.2,
        source_artifacts: {
          a_render_qa_path: "/tmp/variant_a/render_qa.json",
          b_render_qa_path: "/tmp/variant_b/render_qa.json",
        },
        details: "Default fair-listen applies +1.2 dB to B using render_qa mean integrated LUFS (A=-14, B=-15.2).",
      },
    }));
    await page.locator("#compare-a-qa-file-input").setInputFiles(jsonFile("a.render_qa.json", {
      jobs: [
        {
          job_id: "JOB.001",
          outputs: [
            {
              path: "variant_a/mix.wav",
              metrics: {
                integrated_lufs: -14.0,
                rms_dbfs: -10.0,
              },
            },
          ],
        },
      ],
    }));
    await page.locator("#compare-b-qa-file-input").setInputFiles(jsonFile("b.render_qa.json", {
      jobs: [
        {
          job_id: "JOB.001",
          outputs: [
            {
              path: "variant_b/mix.wav",
              metrics: {
                integrated_lufs: -15.2,
                rms_dbfs: -11.0,
              },
            },
          ],
        },
      ],
    }));

    await expect(page.locator("#ab-compensation")).toContainText("Fair listen on");
    await expect(page.locator("#compare-compensation-input")).toHaveValue("1.2");
    await expect(page.locator("#compare-change-summary")).toContainText("Stereo coherence -0.16");
    await expect(page.locator("#compare-summary")).toContainText("Profile changed");
    await expect(page.locator("#compare-summary-note")).toContainText("evaluation_only=true");
    await page.getByRole("button", { name: "B", exact: true }).click();
    await expect(page.locator("#compare-readout-primary")).toContainText("variant_b");
    await expect(page.locator("#compare-readout-secondary")).toContainText("raw=-15.2");

    await page.locator("#compare-summary-hint-trigger").focus();
    await expect(page.locator("#hint-compare-summary")).toBeVisible();
    await expect(page.locator("#hint-compare-summary")).toContainText("What:");
  });
});

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
      "widget.compare.ab_toggle",
      "widget.compare.compensation_knob",
      "widget.compare.value_readout",
      "widget.compare.summary",
      "widget.compare.json",
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
      "widget.results.detail_slider",
      "widget.results.value_readout",
      "widget.results.what_changed",
      "widget.results.qa",
      "widget.results.json",
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
      { screen: "results", selector: '[data-widget-id="widget.results.detail_slider"]' },
      { screen: "compare", selector: '[data-widget-id="widget.compare.compensation_knob"]' },
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

  test("scene screen shows generated scene summary plus lint and lock context", async ({ page }) => {
    await page.goto("/");
    await openScreen(page, "scene");

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

    await expect(page.locator("#scene-summary-text")).toContainText("Perspective:");
    await expect(page.locator("#scene-summary-text")).toContainText("OBJ.VOX");
    await expect(page.locator("#scene-locks-text")).toContainText("LOCK.PRESERVE_DYNAMICS");
    await expect(page.locator("#scene-focus-caption")).toContainText("Nearest:");
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
      applied_recommendations: [
        {
          recommendation_id: "REC.RENDER.001",
          action_id: "ACTION.UTILITY.GAIN",
          scope: { stem_id: "STEM.VOX" },
        },
      ],
      blocked_recommendations: [
        {
          recommendation_id: "REC.RENDER.002",
          gate_summary: "blocked_by_gates",
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
      jobs: [
        {
          job_id: "JOB.001",
          outputs: [
            {
              path: "render/2_0/mix.wav",
              metrics: {
                integrated_lufs: -14.1,
                rms_dbfs: -10.2,
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
    await expect(page.locator("#results-what-changed-text")).toContainText("render/2_0/mix.wav");
    await expect(page.locator("#results-qa-text")).toContainText("ISSUE.RENDER.QA.TRUE_PEAK_WARN");
    await expect(page.locator("#artifact-browser-list")).toContainText("render/2_0/mix.wav");
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
      notes: [
        "Profile changed: PROFILE.ASSIST -> PROFILE.FULL_SEND.",
        "Translation risk moved upward: low -> medium.",
      ],
      warnings: [
        "Translation risk increased from A to B; verify on small speakers before choosing.",
      ],
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

    await expect(page.locator("#ab-compensation")).toContainText("loudness-matched");
    await expect(page.locator("#compare-compensation-input")).toHaveValue("1.2");
    await expect(page.locator("#compare-summary")).toContainText("Profile changed");
    await page.getByRole("button", { name: "B", exact: true }).click();
    await expect(page.locator("#compare-readout-primary")).toContainText("variant_b");
    await expect(page.locator("#compare-readout-secondary")).toContainText("raw=-15.2");
  });
});

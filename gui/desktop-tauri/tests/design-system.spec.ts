import { expect, test } from "@playwright/test"

type ScreenKey = "dashboard" | "presets" | "run" | "compare"

type WidgetBox = {
  bottom: number
  height: number
  right: number
  widgetId: string
  width: number
  x: number
  y: number
}

const screens: Record<ScreenKey, { buttonLabel: string; requiredWidgets: string[] }> = {
  dashboard: {
    buttonLabel: "Dashboard",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.dashboard.signal_vibe",
      "widget.dashboard.signal_safety",
      "widget.dashboard.signal_deliverables",
      "widget.dashboard.knob_width",
      "widget.dashboard.slider_trim",
      "widget.dashboard.toggle_safe_mode",
      "widget.dashboard.segmented_perspective",
      "widget.dashboard.xy_focus",
      "widget.dashboard.value_readout",
    ],
  },
  presets: {
    buttonLabel: "Presets",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.presets.browser",
    ],
  },
  run: {
    buttonLabel: "Run",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.run.stems_folder",
      "widget.run.workspace_folder",
      "widget.run.render_target",
      "widget.run.layout_standard",
      "widget.run.actions",
      "widget.run.status",
      "widget.run.stages",
      "widget.run.details",
    ],
  },
  compare: {
    buttonLabel: "Compare",
    requiredWidgets: [
      "widget.header.scale",
      "widget.header.fine_adjust",
      "widget.header.tabs",
      "widget.compare.ab_toggle",
      "widget.compare.value_readout",
      "widget.compare.summary",
    ],
  },
}

const viewports = [
  { label: "mobile", width: 390, height: 844 },
  { label: "laptop", width: 1280, height: 900 },
  { label: "desktop", width: 1728, height: 1117 },
]

function overlaps(left: WidgetBox, right: WidgetBox): boolean {
  const gutter = 1
  return (
    left.x < (right.right - gutter)
    && (left.right - gutter) > right.x
    && left.y < (right.bottom - gutter)
    && (left.bottom - gutter) > right.y
  )
}

async function openScreen(page: Parameters<typeof test>[0]["page"], screen: ScreenKey): Promise<void> {
  await page.getByRole("button", { name: screens[screen].buttonLabel, exact: true }).click()
  await expect(page.locator(`#screen-${screen}`)).toBeVisible()
}

async function visibleWidgetBoxes(page: Parameters<typeof test>[0]["page"]): Promise<WidgetBox[]> {
  return await page.locator("[data-widget-id]").evaluateAll((nodes) => {
    return nodes.flatMap((node) => {
      if (!(node instanceof HTMLElement)) {
        return []
      }
      const style = window.getComputedStyle(node)
      if (style.display === "none" || style.visibility === "hidden" || node.hidden) {
        return []
      }
      const rect = node.getBoundingClientRect()
      if (rect.width < 1 || rect.height < 1) {
        return []
      }
      return [{
        widgetId: node.dataset.widgetId ?? "",
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        right: rect.right,
        bottom: rect.bottom,
      }]
    })
  })
}

test.describe("desktop design system", () => {
  for (const viewport of viewports) {
    test(`widgets stay on-screen without overlaps at ${viewport.label}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto("/")

      for (const screen of Object.keys(screens) as ScreenKey[]) {
        await openScreen(page, screen)
        const boxes = await visibleWidgetBoxes(page)
        const boxIds = new Set(boxes.map((box) => box.widgetId))

        for (const requiredWidget of screens[screen].requiredWidgets) {
          expect(boxIds.has(requiredWidget)).toBeTruthy()
          const locator = page.locator(`[data-widget-id="${requiredWidget}"]`)
          await locator.scrollIntoViewIfNeeded()
          const widgetBox = await locator.boundingBox()
          expect(widgetBox).not.toBeNull()
          if (widgetBox === null) {
            continue
          }
          expect(widgetBox.x).toBeGreaterThanOrEqual(0)
          expect(widgetBox.y).toBeGreaterThanOrEqual(0)
          expect(widgetBox.x + widgetBox.width).toBeLessThanOrEqual(viewport.width)
          expect(widgetBox.y + widgetBox.height).toBeLessThanOrEqual(viewport.height)
        }

        for (let index = 0; index < boxes.length; index += 1) {
          for (let otherIndex = index + 1; otherIndex < boxes.length; otherIndex += 1) {
            expect(overlaps(boxes[index] as WidgetBox, boxes[otherIndex] as WidgetBox)).toBeFalsy()
          }
        }
      }
    })
  }

  test("numeric controls expose units and exact entry fields", async ({ page }) => {
    await page.goto("/")
    await openScreen(page, "dashboard")

    const numericWidgets = page.locator(
      '[data-control-kind="KNOB"], [data-control-kind="SLIDER"], [data-control-kind="XY"]',
    )
    await expect(numericWidgets).toHaveCount(3)

    const widgetCount = await numericWidgets.count()
    for (let index = 0; index < widgetCount; index += 1) {
      const widget = numericWidgets.nth(index)
      await expect(widget.locator(".control-unit").first()).toBeVisible()
      await expect(widget.locator('input[type="number"]').first()).toBeVisible()
    }

    const knobInput = page.locator("#width-knob-input")
    await knobInput.fill("3.4")
    await knobInput.press("Tab")
    await expect(page.locator("#width-knob-value")).toContainText("+3.4 dB")
  })

  test("global scale control and fine adjust modifier feedback are active", async ({ page }) => {
    await page.goto("/")
    await openScreen(page, "dashboard")

    await page.getByRole("button", { name: "115%", exact: true }).click()
    await expect(page.locator("html")).toHaveAttribute("data-gui-scale", "comfort")
    const scale = await page.locator("html").evaluate((element) => {
      return window.getComputedStyle(element).getPropertyValue("--gui-scale").trim()
    })
    expect(scale).toBe("1.15")

    const sliderInput = page.locator("#trim-slider-input")
    const slider = page.locator("#trim-slider")
    const sliderBox = await slider.boundingBox()
    expect(sliderBox).not.toBeNull()
    if (sliderBox === null) {
      return
    }

    await sliderInput.fill("0")
    await sliderInput.press("Tab")
    await page.mouse.move(sliderBox.x + (sliderBox.width / 2), sliderBox.y + (sliderBox.height / 2))
    await page.mouse.down()
    await page.mouse.move(sliderBox.x + (sliderBox.width / 2) + 90, sliderBox.y + (sliderBox.height / 2))
    await page.mouse.up()
    const coarseValue = Number(await sliderInput.inputValue())

    await sliderInput.fill("0")
    await sliderInput.press("Tab")
    await page.keyboard.down("Shift")
    await page.mouse.move(sliderBox.x + (sliderBox.width / 2), sliderBox.y + (sliderBox.height / 2))
    await page.mouse.down()
    await page.mouse.move(sliderBox.x + (sliderBox.width / 2) + 90, sliderBox.y + (sliderBox.height / 2))
    await expect(page.locator("#fine-adjust-indicator")).toContainText("Fine adjust active")
    await page.mouse.up()
    const fineValue = Number(await sliderInput.inputValue())
    await page.keyboard.up("Shift")

    expect(Math.abs(fineValue)).toBeLessThan(Math.abs(coarseValue))
  })
})

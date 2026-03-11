type ScreenKey = "dashboard" | "presets" | "run" | "compare"
type PerspectiveKey = "audience" | "band" | "orchestra"
type CompareState = "A" | "B"
type DragKind = "width" | "trim" | "focus"
type ModifierState = {
  ctrlKeyActive: boolean
  shiftKeyActive: boolean
}

type ScalePreset = {
  factor: number
  label: string
  scaleId: string
}

type PresetSpec = {
  compareCompensationDb: number
  focusDepth: number
  focusPan: number
  name: string
  presetId: string
  summary: string
  tags: string[]
  trimDb: number
  widthDb: number
}

type DragState = {
  kind: DragKind
  pointerId: number | null
  usesPointerEvents: boolean
  rect: DOMRect
  startFocusDepth: number
  startFocusPan: number
  startTrimDb: number
  startWidthDb: number
  startX: number
  startY: number
}

type DragGestureEvent = MouseEvent | PointerEvent

const SCALE_PRESETS: ScalePreset[] = [
  { scaleId: "compact", label: "90%", factor: 0.9 },
  { scaleId: "standard", label: "100%", factor: 1.0 },
  { scaleId: "comfort", label: "115%", factor: 1.15 },
]

const PRESETS: PresetSpec[] = [
  {
    presetId: "preset.translation_safe",
    name: "Translation Safe",
    summary: "Keeps the center anchored while trimming broad stereo bloom.",
    tags: ["Safe", "Punch"],
    widthDb: 1.5,
    trimDb: -3.2,
    focusPan: 8,
    focusDepth: 62,
    compareCompensationDb: -0.6,
  },
  {
    presetId: "preset.wide_cinematic",
    name: "Wide Cinematic",
    summary: "Expands width and depth for choruses without pushing the master harder.",
    tags: ["Wide", "Air"],
    widthDb: 4.8,
    trimDb: -4.1,
    focusPan: 18,
    focusDepth: 74,
    compareCompensationDb: -0.8,
  },
  {
    presetId: "preset.warm_intimate",
    name: "Warm Intimate",
    summary: "Pulls the image inward and forward for a denser, singer-led feel.",
    tags: ["Warm", "Safe"],
    widthDb: 0.4,
    trimDb: -2.4,
    focusPan: 3,
    focusDepth: 48,
    compareCompensationDb: -0.4,
  },
  {
    presetId: "preset.punchy_tight",
    name: "Punchy Tight",
    summary: "Narrows the sides slightly so transient detail feels more immediate.",
    tags: ["Punch", "Safe"],
    widthDb: -0.8,
    trimDb: -2.9,
    focusPan: -4,
    focusDepth: 58,
    compareCompensationDb: -0.3,
  },
]

const PERSPECTIVE_COPY: Record<PerspectiveKey, string> = {
  audience: "Audience keeps the front image broad and the depth slightly pulled back.",
  band: "Band moves focus closer so timing and punch stay obvious while editing.",
  orchestra: "Orchestra opens the stage and prioritizes depth over center density.",
}

const ui = {
  abButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#ab-toggle [data-ab-state]")),
  abCompensation: requiredElement<HTMLElement>("#ab-compensation"),
  compareReadoutPrimary: requiredElement<HTMLElement>("#compare-readout-primary"),
  compareReadoutSecondary: requiredElement<HTMLElement>("#compare-readout-secondary"),
  compareSummary: requiredElement<HTMLElement>("#compare-summary"),
  compareSummaryNote: requiredElement<HTMLElement>("#compare-summary-note"),
  depthInput: requiredElement<HTMLInputElement>("#focus-depth-input"),
  fineAdjustIndicator: requiredElement<HTMLElement>("#fine-adjust-indicator"),
  focusCaption: requiredElement<HTMLElement>("#focus-caption"),
  focusDot: requiredElement<HTMLElement>("#focus-xy-dot"),
  focusPad: requiredElement<HTMLButtonElement>("#focus-xy-pad"),
  guiScaleButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#gui-scale-control [data-scale-id]")),
  guiScaleLabel: requiredElement<HTMLElement>("#gui-scale-label"),
  knobInput: requiredElement<HTMLInputElement>("#width-knob-input"),
  knobSurface: requiredElement<HTMLButtonElement>("#width-knob"),
  knobValue: requiredElement<HTMLElement>("#width-knob-value"),
  panInput: requiredElement<HTMLInputElement>("#focus-pan-input"),
  perspectiveButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#perspective-segmented [data-perspective]")),
  perspectiveCaption: requiredElement<HTMLElement>("#perspective-caption"),
  presetBrowserList: requiredElement<HTMLElement>("#preset-browser-list"),
  presetPreviewDelta: requiredElement<HTMLElement>("#preset-preview-delta"),
  presetPreviewName: requiredElement<HTMLElement>("#preset-preview-name"),
  presetPreviewSummary: requiredElement<HTMLElement>("#preset-preview-summary"),
  presetSearch: requiredElement<HTMLInputElement>("#preset-search"),
  presetTagButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#preset-tag-row [data-preset-tag]")),
  safeModeState: requiredElement<HTMLElement>("#safe-mode-state"),
  safeModeToggle: requiredElement<HTMLButtonElement>("#safe-mode-toggle"),
  screenPanels: Array.from(document.querySelectorAll<HTMLElement>("[data-screen-panel]")),
  screenTabs: Array.from(document.querySelectorAll<HTMLButtonElement>("[data-screen-target]")),
  sliderFill: requiredElement<HTMLElement>("#trim-slider-fill"),
  sliderInput: requiredElement<HTMLInputElement>("#trim-slider-input"),
  sliderSurface: requiredElement<HTMLButtonElement>("#trim-slider"),
  sliderValue: requiredElement<HTMLElement>("#trim-slider-value"),
  valueReadoutFocus: requiredElement<HTMLElement>("#value-readout-focus"),
  valueReadoutLufs: requiredElement<HTMLElement>("#value-readout-lufs"),
  valueReadoutNote: requiredElement<HTMLElement>("#value-readout-note"),
}

const state = {
  compareState: "A" as CompareState,
  fineAdjustContext: null as string | null,
  modifierState: {
    ctrlKeyActive: false,
    shiftKeyActive: false,
  } as ModifierState,
  perspective: "audience" as PerspectiveKey,
  presetId: PRESETS[0]?.presetId ?? "",
  scaleId: "standard",
  screen: "dashboard" as ScreenKey,
  search: "",
  selectedTag: "ALL",
  safeMode: true,
  trimDb: -3.2,
  widthDb: 1.5,
  focusPan: 8,
  focusDepth: 62,
}

let dragState: DragState | null = null

function requiredElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector)
  if (element === null) {
    throw new Error(`Missing required design-system node: ${selector}`)
  }
  return element
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}

function roundToStep(value: number, step: number): number {
  return Math.round(value / step) * step
}

function signedNumber(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits))
  if (Object.is(rounded, -0)) {
    return "0.0"
  }
  return rounded > 0 ? `+${rounded.toFixed(digits)}` : rounded.toFixed(digits)
}

function currentPreset(): PresetSpec {
  return PRESETS.find((preset) => preset.presetId === state.presetId) ?? PRESETS[0]
}

function hasFineAdjustModifier(): boolean {
  return state.modifierState.shiftKeyActive || state.modifierState.ctrlKeyActive
}

function syncModifierState(event: Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "shiftKey">): void {
  state.modifierState.shiftKeyActive = event.shiftKey
  state.modifierState.ctrlKeyActive = event.ctrlKey || event.metaKey
}

function resetModifierState(): void {
  state.modifierState.shiftKeyActive = false
  state.modifierState.ctrlKeyActive = false
}

function isFineAdjust(event?: Pick<KeyboardEvent | MouseEvent | PointerEvent, "ctrlKey" | "metaKey" | "shiftKey">): boolean {
  return Boolean(event?.shiftKey || event?.ctrlKey || event?.metaKey || hasFineAdjustModifier())
}

function isPointerGestureEvent(event: DragGestureEvent): event is PointerEvent {
  return typeof PointerEvent !== "undefined" && event instanceof PointerEvent
}

function updateFineAdjustIndicator(): void {
  const active = hasFineAdjustModifier() || state.fineAdjustContext !== null
  ui.fineAdjustIndicator.classList.toggle("is-active", active)
  if (active) {
    const suffix = state.fineAdjustContext ? ` · ${state.fineAdjustContext}` : ""
    ui.fineAdjustIndicator.textContent = `Fine adjust active${suffix}.`
    return
  }
  ui.fineAdjustIndicator.textContent = "Hold Shift or Ctrl for fine adjust."
}

function updateScale(): void {
  const preset = SCALE_PRESETS.find((item) => item.scaleId === state.scaleId) ?? SCALE_PRESETS[1]
  document.documentElement.style.setProperty("--gui-scale", preset.factor.toString())
  document.documentElement.dataset.guiScale = preset.scaleId
  ui.guiScaleLabel.textContent = `Scale set to ${preset.label}.`

  for (const button of ui.guiScaleButtons) {
    const active = button.dataset.scaleId === preset.scaleId
    button.classList.toggle("is-active", active)
    button.setAttribute("aria-pressed", active ? "true" : "false")
  }
}

function updateScreens(): void {
  for (const panel of ui.screenPanels) {
    panel.hidden = panel.dataset.screenPanel !== state.screen
  }
  for (const button of ui.screenTabs) {
    const active = button.dataset.screenTarget === state.screen
    button.setAttribute("aria-pressed", active ? "true" : "false")
  }
}

function updateSafeMode(): void {
  ui.safeModeState.textContent = state.safeMode ? "On" : "Off"
  ui.safeModeState.classList.toggle("status-chip-ok", state.safeMode)
  ui.safeModeToggle.classList.toggle("is-active", state.safeMode)
  ui.safeModeToggle.textContent = state.safeMode ? "Safe mode enabled" : "Safe mode disabled"
}

function updatePerspective(): void {
  for (const button of ui.perspectiveButtons) {
    const active = button.dataset.perspective === state.perspective
    button.classList.toggle("is-active", active)
    button.setAttribute("aria-pressed", active ? "true" : "false")
  }
  ui.perspectiveCaption.textContent = PERSPECTIVE_COPY[state.perspective]
}

function updateWidthKnob(): void {
  const ratio = (state.widthDb + 12) / 24
  ui.knobSurface.style.setProperty("--control-ratio", ratio.toFixed(4))
  ui.knobSurface.setAttribute("aria-valuenow", state.widthDb.toFixed(1))
  ui.knobInput.value = state.widthDb.toFixed(1)
  ui.knobValue.textContent = `${signedNumber(state.widthDb)} dB width trim`
}

function updateTrimSlider(): void {
  const ratio = (state.trimDb + 18) / 24
  ui.sliderFill.style.setProperty("--slider-ratio", ratio.toFixed(4))
  ui.sliderSurface.style.setProperty("--slider-ratio", ratio.toFixed(4))
  ui.sliderSurface.setAttribute("aria-valuenow", state.trimDb.toFixed(1))
  ui.sliderInput.value = state.trimDb.toFixed(1)
  ui.sliderValue.textContent = `${signedNumber(state.trimDb)} dB output trim`
}

function updateFocusPad(): void {
  const normalizedX = ((state.focusPan + 45) / 90) * 100
  ui.focusDot.style.setProperty("--xy-x", clamp(normalizedX, 0, 100).toFixed(3))
  ui.focusDot.style.setProperty("--xy-y", clamp(state.focusDepth, 0, 100).toFixed(3))
  ui.panInput.value = Math.round(state.focusPan).toString()
  ui.depthInput.value = Math.round(state.focusDepth).toString()
  ui.focusCaption.textContent = `Pan ${Math.round(state.focusPan)} deg · Depth ${Math.round(state.focusDepth)}%`
}

function updateReadouts(): void {
  const preset = currentPreset()
  const loudness = -14.2 + (state.trimDb * 0.34) + (state.widthDb * 0.06) + (state.safeMode ? -0.1 : 0.2)
  ui.valueReadoutLufs.textContent = `${loudness.toFixed(1)} LUFS`
  ui.valueReadoutFocus.textContent = `Pan ${Math.round(state.focusPan)} deg · Depth ${Math.round(state.focusDepth)}%`
  ui.valueReadoutNote.textContent = `${preset.name}: ${preset.summary}`
}

function updateCompare(): void {
  const preset = currentPreset()
  const compensationDb = state.compareState === "A" ? 0 : preset.compareCompensationDb
  const loudness = -14.2 + compensationDb

  for (const button of ui.abButtons) {
    const active = button.dataset.abState === state.compareState
    button.classList.toggle("is-active", active)
    button.setAttribute("aria-pressed", active ? "true" : "false")
  }

  ui.abCompensation.textContent = state.compareState === "A"
    ? "State A is the reference pass."
    : `State B is matched by ${signedNumber(compensationDb)} dB before comparison.`
  ui.compareReadoutPrimary.textContent = `${loudness.toFixed(1)} LUFS`
  ui.compareReadoutSecondary.textContent = `Width ${signedNumber(state.widthDb)} dB · Trim ${signedNumber(state.trimDb)} dB`
  ui.compareSummary.textContent = state.compareState === "A"
    ? "Version A stays tighter with a slightly stronger phantom center."
    : "Version B opens the sides while staying loudness-matched for a fair listen."
  ui.compareSummaryNote.textContent = `${preset.name} keeps the compensation explicit so the comparison stays about tone and space.`
}

function filteredPresets(): PresetSpec[] {
  const query = state.search.trim().toLowerCase()
  return PRESETS.filter((preset) => {
    const matchesTag = state.selectedTag === "ALL" || preset.tags.includes(state.selectedTag)
    const haystack = `${preset.name} ${preset.summary} ${preset.tags.join(" ")}`.toLowerCase()
    const matchesQuery = !query || haystack.includes(query)
    return matchesTag && matchesQuery
  })
}

function renderPresetBrowser(): void {
  const presets = filteredPresets()
  ui.presetBrowserList.replaceChildren()

  for (const button of ui.presetTagButtons) {
    button.classList.toggle("is-active", button.dataset.presetTag === state.selectedTag)
  }

  if (presets.length === 0) {
    const emptyState = document.createElement("p")
    emptyState.className = "control-caption"
    emptyState.textContent = "No presets match this search yet."
    ui.presetBrowserList.append(emptyState)
  }

  for (const preset of presets) {
    const button = document.createElement("button")
    button.type = "button"
    button.className = "preset-button"
    button.dataset.presetId = preset.presetId
    button.classList.toggle("is-active", preset.presetId === state.presetId)
    button.innerHTML = `<strong>${preset.name}</strong><small>${preset.tags.join(" · ")}</small>`
    ui.presetBrowserList.append(button)
  }

  const preview = currentPreset()
  ui.presetPreviewName.textContent = preview.name
  ui.presetPreviewSummary.textContent = preview.summary
  ui.presetPreviewDelta.textContent = `Width ${signedNumber(preview.widthDb)} dB · Trim ${signedNumber(preview.trimDb)} dB · Focus ${preview.focusPan} deg / ${preview.focusDepth}%`
}

function syncAll(): void {
  updateFineAdjustIndicator()
  updateScale()
  updateScreens()
  updateSafeMode()
  updatePerspective()
  updateWidthKnob()
  updateTrimSlider()
  updateFocusPad()
  updateReadouts()
  updateCompare()
  renderPresetBrowser()
}

function applyPreset(presetId: string): void {
  const preset = PRESETS.find((item) => item.presetId === presetId)
  if (preset === undefined) {
    return
  }
  state.presetId = preset.presetId
  state.widthDb = preset.widthDb
  state.trimDb = preset.trimDb
  state.focusPan = preset.focusPan
  state.focusDepth = preset.focusDepth
  syncAll()
}

function startDrag(kind: DragKind, event: DragGestureEvent): void {
  if (dragState !== null) {
    return
  }
  const target = event.currentTarget
  if (!(target instanceof HTMLElement)) {
    return
  }
  event.preventDefault()
  dragState = {
    kind,
    pointerId: isPointerGestureEvent(event) ? event.pointerId : null,
    usesPointerEvents: isPointerGestureEvent(event),
    rect: target.getBoundingClientRect(),
    startFocusDepth: state.focusDepth,
    startFocusPan: state.focusPan,
    startTrimDb: state.trimDb,
    startWidthDb: state.widthDb,
    startX: event.clientX,
    startY: event.clientY,
  }
  if (isPointerGestureEvent(event)) {
    try {
      target.setPointerCapture(event.pointerId)
    } catch {
      // Firefox can reject synthetic pointer capture in automation; window listeners still drive the drag.
    }
  }
  state.fineAdjustContext = isFineAdjust(event)
    ? dragLabel(kind)
    : null
  updateFineAdjustIndicator()
}

function dragLabel(kind: DragKind): string {
  switch (kind) {
    case "width":
      return "Width"
    case "trim":
      return "Trim"
    case "focus":
      return "Focus"
  }
}

function updateFromDrag(event: DragGestureEvent): void {
  if (dragState === null) {
    return
  }
  const pointerEvent = isPointerGestureEvent(event)
  if (dragState.usesPointerEvents) {
    if (!pointerEvent || dragState.pointerId !== event.pointerId) {
      return
    }
  } else if (pointerEvent || event.buttons === 0) {
    return
  }
  const fine = isFineAdjust(event)
  state.fineAdjustContext = fine ? dragLabel(dragState.kind) : null

  if (dragState.kind === "width") {
    const multiplier = fine ? 0.04 : 0.14
    const delta = dragState.startY - event.clientY
    state.widthDb = clamp(roundToStep(dragState.startWidthDb + (delta * multiplier), fine ? 0.05 : 0.1), -12, 12)
  }

  if (dragState.kind === "trim") {
    const multiplier = fine ? 0.025 : 0.11
    const delta = event.clientX - dragState.startX
    state.trimDb = clamp(roundToStep(dragState.startTrimDb + (delta * multiplier), fine ? 0.05 : 0.1), -18, 6)
  }

  if (dragState.kind === "focus") {
    const xRatio = clamp((event.clientX - dragState.rect.left) / dragState.rect.width, 0, 1)
    const depthRatio = clamp(1 - ((event.clientY - dragState.rect.top) / dragState.rect.height), 0, 1)
    const targetPan = (xRatio * 90) - 45
    const targetDepth = depthRatio * 100
    const blend = fine ? 0.28 : 1
    state.focusPan = clamp(
      roundToStep(dragState.startFocusPan + ((targetPan - dragState.startFocusPan) * blend), 1),
      -45,
      45,
    )
    state.focusDepth = clamp(
      roundToStep(dragState.startFocusDepth + ((targetDepth - dragState.startFocusDepth) * blend), 1),
      0,
      100,
    )
  }

  syncAll()
}

function endDrag(event: DragGestureEvent): void {
  if (dragState === null) {
    return
  }
  const pointerEvent = isPointerGestureEvent(event)
  if (dragState.usesPointerEvents) {
    if (!pointerEvent || dragState.pointerId !== event.pointerId) {
      return
    }
  } else if (pointerEvent) {
    return
  }
  dragState = null
  state.fineAdjustContext = null
  updateFineAdjustIndicator()
}

function bindModifierFeedback(): void {
  window.addEventListener("keydown", (event) => {
    syncModifierState(event)
    if (!hasFineAdjustModifier()) {
      return
    }
    updateFineAdjustIndicator()
  })

  window.addEventListener("keyup", (event) => {
    syncModifierState(event)
    if (dragState === null && !hasFineAdjustModifier()) {
      state.fineAdjustContext = null
    }
    updateFineAdjustIndicator()
  })

  window.addEventListener("blur", () => {
    resetModifierState()
    if (dragState === null) {
      state.fineAdjustContext = null
    }
    updateFineAdjustIndicator()
  })

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      return
    }
    resetModifierState()
    if (dragState === null) {
      state.fineAdjustContext = null
    }
    updateFineAdjustIndicator()
  })
}

function bindScreens(): void {
  for (const button of ui.screenTabs) {
    button.addEventListener("click", () => {
      const nextScreen = button.dataset.screenTarget as ScreenKey | undefined
      if (nextScreen === undefined) {
        return
      }
      state.screen = nextScreen
      updateScreens()
    })
  }
}

function bindScale(): void {
  for (const button of ui.guiScaleButtons) {
    button.addEventListener("click", () => {
      const scaleId = button.dataset.scaleId
      if (!scaleId) {
        return
      }
      state.scaleId = scaleId
      updateScale()
    })
  }
}

function bindCompositeControlFocus(): void {
  const keepFocusLocal = (event: KeyboardEvent, nextTarget: HTMLElement): void => {
    if (event.key !== "Tab" || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) {
      return
    }
    event.preventDefault()
    nextTarget.focus({ preventScroll: true })
  }

  ui.knobInput.addEventListener("keydown", (event) => {
    keepFocusLocal(event, ui.knobSurface)
  })
  ui.sliderInput.addEventListener("keydown", (event) => {
    keepFocusLocal(event, ui.sliderSurface)
  })
  ui.panInput.addEventListener("keydown", (event) => {
    keepFocusLocal(event, ui.focusPad)
  })
  ui.depthInput.addEventListener("keydown", (event) => {
    keepFocusLocal(event, ui.focusPad)
  })
}

function bindControls(): void {
  ui.safeModeToggle.addEventListener("click", () => {
    state.safeMode = !state.safeMode
    updateSafeMode()
    updateReadouts()
    updateCompare()
  })

  for (const button of ui.perspectiveButtons) {
    button.addEventListener("click", () => {
      const perspective = button.dataset.perspective as PerspectiveKey | undefined
      if (perspective === undefined) {
        return
      }
      state.perspective = perspective
      updatePerspective()
    })
  }

  ui.knobSurface.addEventListener("pointerdown", (event) => {
    startDrag("width", event)
  })
  ui.knobSurface.addEventListener("mousedown", (event) => {
    startDrag("width", event)
  })
  ui.sliderSurface.addEventListener("pointerdown", (event) => {
    startDrag("trim", event)
  })
  ui.sliderSurface.addEventListener("mousedown", (event) => {
    startDrag("trim", event)
  })
  ui.focusPad.addEventListener("pointerdown", (event) => {
    startDrag("focus", event)
  })
  ui.focusPad.addEventListener("mousedown", (event) => {
    startDrag("focus", event)
  })

  window.addEventListener("pointermove", updateFromDrag)
  window.addEventListener("mousemove", updateFromDrag)
  window.addEventListener("pointerup", endDrag)
  window.addEventListener("mouseup", endDrag)
  window.addEventListener("pointercancel", endDrag)

  ui.knobInput.addEventListener("change", () => {
    const next = Number(ui.knobInput.value)
    if (Number.isFinite(next)) {
      state.widthDb = clamp(roundToStep(next, 0.1), -12, 12)
      updateWidthKnob()
      updateReadouts()
      updateCompare()
    }
  })

  ui.sliderInput.addEventListener("change", () => {
    const next = Number(ui.sliderInput.value)
    if (Number.isFinite(next)) {
      state.trimDb = clamp(roundToStep(next, 0.1), -18, 6)
      updateTrimSlider()
      updateReadouts()
      updateCompare()
    }
  })

  ui.panInput.addEventListener("change", () => {
    const next = Number(ui.panInput.value)
    if (Number.isFinite(next)) {
      state.focusPan = clamp(roundToStep(next, 1), -45, 45)
      updateFocusPad()
      updateReadouts()
    }
  })

  ui.depthInput.addEventListener("change", () => {
    const next = Number(ui.depthInput.value)
    if (Number.isFinite(next)) {
      state.focusDepth = clamp(roundToStep(next, 1), 0, 100)
      updateFocusPad()
      updateReadouts()
    }
  })

  ui.presetSearch.addEventListener("input", () => {
    state.search = ui.presetSearch.value
    renderPresetBrowser()
  })

  for (const button of ui.presetTagButtons) {
    button.addEventListener("click", () => {
      state.selectedTag = button.dataset.presetTag ?? "ALL"
      renderPresetBrowser()
    })
  }

  ui.presetBrowserList.addEventListener("click", (event) => {
    const target = event.target
    if (!(target instanceof HTMLElement)) {
      return
    }
    const button = target.closest<HTMLButtonElement>("[data-preset-id]")
    if (button === null) {
      return
    }
    const presetId = button.dataset.presetId
    if (!presetId) {
      return
    }
    applyPreset(presetId)
  })

  for (const button of ui.abButtons) {
    button.addEventListener("click", () => {
      const compareState = button.dataset.abState as CompareState | undefined
      if (compareState === undefined) {
        return
      }
      state.compareState = compareState
      updateCompare()
    })
  }
}

export function initDesignSystem(): void {
  bindModifierFeedback()
  bindScreens()
  bindScale()
  bindCompositeControlFocus()
  bindControls()
  syncAll()
}

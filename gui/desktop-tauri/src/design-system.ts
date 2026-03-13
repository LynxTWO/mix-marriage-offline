export type ScreenKey =
  | "validate"
  | "analyze"
  | "scene"
  | "render"
  | "results"
  | "compare";

type ScaleId = "compact" | "standard" | "comfort";
type ModifierLike = Pick<KeyboardEvent | MouseEvent | PointerEvent, "ctrlKey" | "metaKey" | "shiftKey">;

type ScalePreset = {
  factor: number;
  label: string;
  scaleId: ScaleId;
};

type InitOptions = {
  defaultScreen?: ScreenKey;
  onScreenChange?: (screen: ScreenKey) => void;
};

type DesignSystemController = {
  getScreen: () => ScreenKey;
  isFineAdjust: (event?: ModifierLike) => boolean;
  setFineAdjustContext: (label: string | null) => void;
  setScreen: (screen: ScreenKey) => void;
};

const SCALE_PRESETS: ScalePreset[] = [
  { scaleId: "compact", label: "90%", factor: 0.9 },
  { scaleId: "standard", label: "100%", factor: 1.0 },
  { scaleId: "comfort", label: "115%", factor: 1.15 },
];

function requiredElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (element === null) {
    throw new Error(`Missing required design-system node: ${selector}`);
  }
  return element;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

export function roundToStep(value: number, step: number): number {
  return Math.round(value / step) * step;
}

export function signedNumber(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits));
  if (Object.is(rounded, -0)) {
    return "0.0";
  }
  return rounded > 0 ? `+${rounded.toFixed(digits)}` : rounded.toFixed(digits);
}

export function signedDb(value: number, digits = 1): string {
  return `${signedNumber(value, digits)} dB`;
}

export function initDesignSystem(options: InitOptions = {}): DesignSystemController {
  const scaleButtons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("#gui-scale-control [data-scale-id]"),
  );
  const screenButtons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("[data-screen-target]"),
  );
  const screenPanels = Array.from(
    document.querySelectorAll<HTMLElement>("[data-screen-panel]"),
  );
  const fineAdjustIndicator = requiredElement<HTMLElement>("#fine-adjust-indicator");
  const scaleLabel = requiredElement<HTMLElement>("#gui-scale-label");

  const state = {
    ctrlKeyActive: false,
    fineAdjustContext: null as string | null,
    scaleId: "standard" as ScaleId,
    screen: options.defaultScreen ?? "validate",
    shiftKeyActive: false,
  };

  const updateFineAdjustIndicator = () => {
    const active = state.ctrlKeyActive || state.shiftKeyActive || state.fineAdjustContext !== null;
    fineAdjustIndicator.classList.toggle("is-active", active);
    if (active) {
      const suffix = state.fineAdjustContext ? ` · ${state.fineAdjustContext}` : "";
      fineAdjustIndicator.textContent = `Fine adjust active${suffix}.`;
      return;
    }
    fineAdjustIndicator.textContent = "Hold Shift or Ctrl for fine adjust.";
  };

  const updateScale = () => {
    const preset = SCALE_PRESETS.find((item) => item.scaleId === state.scaleId) ?? SCALE_PRESETS[1];
    document.documentElement.style.setProperty("--gui-scale", preset.factor.toString());
    document.documentElement.dataset.guiScale = preset.scaleId;
    scaleLabel.textContent = `Scale set to ${preset.label}.`;

    for (const button of scaleButtons) {
      const active = button.dataset.scaleId === preset.scaleId;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    }
  };

  const updateScreens = () => {
    for (const panel of screenPanels) {
      panel.hidden = panel.dataset.screenPanel !== state.screen;
    }
    for (const button of screenButtons) {
      const active = button.dataset.screenTarget === state.screen;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.classList.toggle("is-active", active);
    }
    options.onScreenChange?.(state.screen);
  };

  const syncModifierState = (event: Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "shiftKey">) => {
    state.shiftKeyActive = event.shiftKey;
    state.ctrlKeyActive = event.ctrlKey || event.metaKey;
    updateFineAdjustIndicator();
  };

  for (const button of scaleButtons) {
    button.addEventListener("click", () => {
      const scaleId = button.dataset.scaleId as ScaleId | undefined;
      if (scaleId === undefined) {
        return;
      }
      state.scaleId = scaleId;
      updateScale();
    });
  }

  for (const button of screenButtons) {
    button.addEventListener("click", () => {
      const screen = button.dataset.screenTarget as ScreenKey | undefined;
      if (screen === undefined) {
        return;
      }
      state.screen = screen;
      updateScreens();
    });
  }

  window.addEventListener("keydown", syncModifierState);
  window.addEventListener("keyup", syncModifierState);
  window.addEventListener("blur", () => {
    state.shiftKeyActive = false;
    state.ctrlKeyActive = false;
    updateFineAdjustIndicator();
  });

  updateScale();
  updateScreens();
  updateFineAdjustIndicator();

  return {
    getScreen: () => state.screen,
    isFineAdjust: (event?: ModifierLike) => {
      return Boolean(
        event?.shiftKey ||
        event?.ctrlKey ||
        event?.metaKey ||
        state.shiftKeyActive ||
        state.ctrlKeyActive,
      );
    },
    setFineAdjustContext: (label: string | null) => {
      state.fineAdjustContext = label;
      updateFineAdjustIndicator();
    },
    setScreen: (screen: ScreenKey) => {
      state.screen = screen;
      updateScreens();
    },
  };
}

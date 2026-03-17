export type ScreenKey =
  | "validate"
  | "analyze"
  | "scene"
  | "render"
  | "results"
  | "compare";

export type ConfidenceTone = "high" | "low" | "medium" | "unknown";

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

export const SCREEN_ORDER: ScreenKey[] = [
  "validate",
  "analyze",
  "scene",
  "render",
  "results",
  "compare",
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

export function formatPercent(value: number | null, digits = 0): string {
  if (value === null || !Number.isFinite(value)) {
    return "n/a";
  }
  return `${(clamp(value, 0, 1) * 100).toFixed(digits)}%`;
}

export function describeConfidence(value: number | null): {
  label: string;
  percentLabel: string;
  tone: ConfidenceTone;
} {
  if (value === null || !Number.isFinite(value)) {
    return {
      label: "Unknown",
      percentLabel: "n/a",
      tone: "unknown",
    };
  }
  if (value >= 0.75) {
    return {
      label: "High",
      percentLabel: formatPercent(value),
      tone: "high",
    };
  }
  if (value >= 0.5) {
    return {
      label: "Medium",
      percentLabel: formatPercent(value),
      tone: "medium",
    };
  }
  return {
    label: "Low",
    percentLabel: formatPercent(value),
    tone: "low",
  };
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
  const screenButtonByKey = new Map<ScreenKey, HTMLButtonElement>();
  for (const button of screenButtons) {
    const key = button.dataset.screenTarget as ScreenKey | undefined;
    if (key !== undefined) {
      screenButtonByKey.set(key, button);
    }
  }

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
      const active = panel.dataset.screenPanel === state.screen;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", active ? "false" : "true");
      panel.tabIndex = active ? 0 : -1;
    }
    for (const button of screenButtons) {
      const active = button.dataset.screenTarget === state.screen;
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.tabIndex = active ? 0 : -1;
      button.classList.toggle("is-active", active);
    }
    options.onScreenChange?.(state.screen);
  };

  const activateScreen = (screen: ScreenKey, focusButton = false) => {
    state.screen = screen;
    updateScreens();
    if (focusButton) {
      screenButtonByKey.get(screen)?.focus({ preventScroll: true });
    }
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
      activateScreen(screen);
    });
    button.addEventListener("keydown", (event) => {
      const currentKey = button.dataset.screenTarget as ScreenKey | undefined;
      if (currentKey === undefined) {
        return;
      }
      const currentIndex = SCREEN_ORDER.indexOf(currentKey);
      if (currentIndex === -1) {
        return;
      }
      let nextIndex = currentIndex;
      if (event.key === "ArrowLeft") {
        nextIndex = currentIndex === 0 ? SCREEN_ORDER.length - 1 : currentIndex - 1;
      } else if (event.key === "ArrowRight") {
        nextIndex = currentIndex === SCREEN_ORDER.length - 1 ? 0 : currentIndex + 1;
      } else if (event.key === "Home") {
        nextIndex = 0;
      } else if (event.key === "End") {
        nextIndex = SCREEN_ORDER.length - 1;
      } else {
        return;
      }
      event.preventDefault();
      activateScreen(SCREEN_ORDER[nextIndex], true);
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
      activateScreen(screen);
    },
  };
}

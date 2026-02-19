function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function _isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function _isPositiveNumber(value) {
  return _isFiniteNumber(value) && value > 0;
}

function _isOptionValue(value) {
  return (
    typeof value === "string"
    || typeof value === "number"
    || typeof value === "boolean"
  );
}

function _toLabel(name) {
  if (typeof name !== "string" || !name) {
    return "";
  }
  return name
    .replace(/[_\-.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function _normalizedType(typeValue) {
  if (typeof typeValue === "string") {
    return typeValue;
  }
  if (Array.isArray(typeValue)) {
    const first = typeValue.find((value) => value !== "null");
    return typeof first === "string" ? first : "";
  }
  return "";
}

function _uiHintMap(uiHints) {
  const map = new Map();
  if (!Array.isArray(uiHints)) {
    return map;
  }
  for (const row of uiHints) {
    if (!_isObject(row)) {
      continue;
    }
    const pointer = row.json_pointer;
    if (typeof pointer !== "string") {
      continue;
    }
    const match = pointer.match(/^\/properties\/([^/]+)\/x_mmo_ui$/);
    if (!match) {
      continue;
    }
    const key = match[1].replace(/~1/g, "/").replace(/~0/g, "~");
    map.set(key, row.hint);
  }
  return map;
}

function _normalizeModifierKey(value) {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized === "alt" || normalized === "ctrl" || normalized === "meta") {
    return normalized;
  }
  return "shift";
}

function _selectOptions(enumValues, hintObject) {
  const explicitOptions = [];
  const options = Array.isArray(hintObject.options) ? hintObject.options : [];
  for (const item of options) {
    if (!_isObject(item)) {
      continue;
    }
    const value = item.value;
    const label = typeof item.label === "string" ? item.label.trim() : "";
    if (!_isOptionValue(value) || !label) {
      continue;
    }
    explicitOptions.push({ value, label });
  }
  if (explicitOptions.length > 0) {
    return explicitOptions;
  }
  return enumValues.map((value) => ({
    value,
    label: String(value),
  }));
}

function _normalizedParamToken(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value
    .trim()
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .toUpperCase();
}

function _decodePointerToken(token) {
  return token.replace(/~1/g, "/").replace(/~0/g, "~");
}

function _resolveFieldNameFromParamRef(paramRef, fieldsByName, fieldsByLowerName, fieldsByCanonical) {
  if (typeof paramRef !== "string") {
    return "";
  }
  const normalized = paramRef.trim();
  if (!normalized) {
    return "";
  }

  if (normalized.startsWith("/")) {
    const parts = normalized
      .split("/")
      .slice(1)
      .map((part) => _decodePointerToken(part));
    if (parts.length >= 2 && parts[0] === "properties") {
      const pointerName = parts[1];
      if (fieldsByName.has(pointerName)) {
        return pointerName;
      }
    }
  }

  if (fieldsByName.has(normalized)) {
    return normalized;
  }
  const byLowerName = fieldsByLowerName.get(normalized.toLowerCase());
  if (typeof byLowerName === "string") {
    return byLowerName;
  }

  const canonicalTail = _normalizedParamToken(normalized.split(".").pop());
  const canonicalMatches = fieldsByCanonical.get(canonicalTail) || [];
  if (canonicalMatches.length === 1) {
    return canonicalMatches[0];
  }
  return "";
}

function _layoutWidgets(uiLayout) {
  if (!_isObject(uiLayout) || uiLayout.present === false) {
    return [];
  }
  const sections = Array.isArray(uiLayout.sections) ? uiLayout.sections : [];
  if (sections.length === 0) {
    return [];
  }
  const widgets = [];
  for (const section of sections) {
    if (!_isObject(section)) {
      continue;
    }
    const sectionWidgets = Array.isArray(section.widgets) ? section.widgets : [];
    for (const widget of sectionWidgets) {
      if (_isObject(widget)) {
        widgets.push(widget);
      }
    }
  }
  return widgets;
}

export function resolveFieldStep(field, modifierState = {}) {
  if (!_isObject(field) || !_isPositiveNumber(field.step)) {
    return null;
  }
  if (!_isPositiveNumber(field.fineStep)) {
    return field.step;
  }
  const modifierKey = _normalizeModifierKey(field.modifierKey);
  const isFine = _isObject(modifierState) && modifierState[modifierKey] === true;
  return isFine ? field.fineStep : field.step;
}

export function orderFieldsByLayout(fields, uiLayout) {
  const normalizedFields = Array.isArray(fields)
    ? fields.filter((field) => _isObject(field) && typeof field.name === "string" && field.name.trim())
    : [];
  if (normalizedFields.length === 0) {
    return { orderedFields: [], moreFields: [], hasLayout: false };
  }

  const widgets = _layoutWidgets(uiLayout);
  if (widgets.length === 0) {
    return { orderedFields: normalizedFields, moreFields: [], hasLayout: false };
  }

  const fieldsByName = new Map(normalizedFields.map((field) => [field.name, field]));
  const fieldsByLowerName = new Map(normalizedFields.map((field) => [field.name.toLowerCase(), field.name]));
  const fieldsByCanonical = new Map();
  for (const field of normalizedFields) {
    const canonical = _normalizedParamToken(field.name);
    if (!canonical) {
      continue;
    }
    const current = fieldsByCanonical.get(canonical) || [];
    current.push(field.name);
    fieldsByCanonical.set(canonical, current);
  }

  const orderedFields = [];
  const seen = new Set();
  for (const widget of widgets) {
    const name = _resolveFieldNameFromParamRef(
      widget.param_ref,
      fieldsByName,
      fieldsByLowerName,
      fieldsByCanonical,
    );
    if (!name || seen.has(name)) {
      continue;
    }
    seen.add(name);
    orderedFields.push(fieldsByName.get(name));
  }

  const moreFields = normalizedFields.filter((field) => !seen.has(field.name));
  return { orderedFields, moreFields, hasLayout: true };
}

export function buildFormFields(configSchema, uiHints = []) {
  if (!_isObject(configSchema)) {
    return [];
  }
  const properties = _isObject(configSchema.properties) ? configSchema.properties : {};
  const requiredRaw = Array.isArray(configSchema.required) ? configSchema.required : [];
  const required = new Set(requiredRaw.filter((value) => typeof value === "string"));
  const hints = _uiHintMap(uiHints);

  return Object.keys(properties)
    .sort()
    .map((name) => {
      const schema = _isObject(properties[name]) ? properties[name] : {};
      const type = _normalizedType(schema.type);
      const enumValues = Array.isArray(schema.enum)
        ? schema.enum.filter((value) => _isOptionValue(value))
        : [];
      const hint = hints.get(name);
      const hintObject = _isObject(hint) ? hint : {};
      const widget = typeof hintObject.widget === "string"
        ? hintObject.widget.trim().toLowerCase()
        : "";

      let inputKind = "json";
      if (widget === "knob" || widget === "fader") {
        inputKind = "range";
      } else if (widget === "toggle") {
        inputKind = "checkbox";
      } else if (widget === "selector") {
        inputKind = "select";
      } else if (enumValues.length > 0) {
        inputKind = "select";
      } else if (type === "boolean") {
        inputKind = "checkbox";
      } else if (type === "number" || type === "integer") {
        inputKind = "number";
      } else if (type === "string") {
        inputKind = "text";
      }

      let step = null;
      if (_isPositiveNumber(hintObject.step)) {
        step = hintObject.step;
      } else if (type === "integer") {
        step = 1;
      }
      const fineStep = _isPositiveNumber(hintObject.fine_step)
        ? hintObject.fine_step
        : null;
      const selectOptions = inputKind === "select" ? _selectOptions(enumValues, hintObject) : [];
      const units = typeof hintObject.units === "string" && hintObject.units.trim()
        ? hintObject.units.trim()
        : null;

      return {
        name,
        label: typeof schema.title === "string" && schema.title.trim() ? schema.title.trim() : _toLabel(name),
        description: typeof schema.description === "string" ? schema.description : "",
        type,
        inputKind,
        widget: widget || null,
        required: required.has(name),
        defaultValue: Object.prototype.hasOwnProperty.call(schema, "default") ? schema.default : null,
        enumValues,
        selectOptions,
        minimum: _isFiniteNumber(hintObject.min)
          ? hintObject.min
          : (_isFiniteNumber(schema.minimum) ? schema.minimum : null),
        maximum: _isFiniteNumber(hintObject.max)
          ? hintObject.max
          : (_isFiniteNumber(schema.maximum) ? schema.maximum : null),
        step,
        fineStep,
        modifierKey: _normalizeModifierKey(hintObject.modifier_key),
        textEntry: hintObject.text_entry === true || inputKind === "range",
        units,
        hint: _isObject(hint) ? hint : null,
      };
    });
}

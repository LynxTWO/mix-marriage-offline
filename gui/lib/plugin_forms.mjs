function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
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
        ? schema.enum.filter((value) => typeof value === "string")
        : [];
      const hint = hints.get(name);
      const hintObject = _isObject(hint) ? hint : {};

      let inputKind = "json";
      if (enumValues.length > 0) {
        inputKind = "select";
      } else if (type === "boolean") {
        inputKind = "checkbox";
      } else if (type === "number" || type === "integer") {
        inputKind = "number";
      } else if (type === "string") {
        inputKind = "text";
      }

      let step = null;
      if (typeof hintObject.step === "number") {
        step = hintObject.step;
      } else if (type === "integer") {
        step = 1;
      }

      return {
        name,
        label: typeof schema.title === "string" && schema.title.trim() ? schema.title.trim() : _toLabel(name),
        description: typeof schema.description === "string" ? schema.description : "",
        type,
        inputKind,
        required: required.has(name),
        defaultValue: Object.prototype.hasOwnProperty.call(schema, "default") ? schema.default : null,
        enumValues,
        minimum: typeof schema.minimum === "number" ? schema.minimum : null,
        maximum: typeof schema.maximum === "number" ? schema.maximum : null,
        step,
        hint: _isObject(hint) ? hint : null,
      };
    });
}

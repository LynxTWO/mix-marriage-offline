import assert from "node:assert/strict";

import { buildFormFields } from "../lib/plugin_forms.mjs";

function _testBuildFormFieldsMapsSchemaAndHints() {
  const schema = {
    type: "object",
    required: ["threshold_db", "enabled"],
    properties: {
      threshold_db: {
        type: "number",
        minimum: -24,
        maximum: 0,
        default: -6,
        description: "Trim threshold in decibels.",
      },
      enabled: {
        type: "boolean",
        default: true,
      },
      mode: {
        type: "string",
        enum: ["safe", "strict"],
        default: "safe",
      },
      comment: {
        type: "string",
      },
    },
  };

  const uiHints = [
    {
      json_pointer: "/properties/threshold_db/x_mmo_ui",
      hint: {
        widget: "fader",
        units: "dB",
        step: 0.5,
      },
    },
  ];

  const fields = buildFormFields(schema, uiHints);
  assert.equal(fields.length, 4);

  const byName = new Map(fields.map((field) => [field.name, field]));
  assert.equal(byName.get("threshold_db").inputKind, "number");
  assert.equal(byName.get("threshold_db").required, true);
  assert.equal(byName.get("threshold_db").step, 0.5);
  assert.equal(byName.get("threshold_db").hint.widget, "fader");

  assert.equal(byName.get("enabled").inputKind, "checkbox");
  assert.equal(byName.get("enabled").required, true);

  assert.equal(byName.get("mode").inputKind, "select");
  assert.deepEqual(byName.get("mode").enumValues, ["safe", "strict"]);

  assert.equal(byName.get("comment").inputKind, "text");
  assert.equal(byName.get("comment").required, false);
}

function _testBuildFormFieldsHandlesInvalidSchema() {
  assert.deepEqual(buildFormFields(null), []);
  assert.deepEqual(buildFormFields([]), []);
  assert.deepEqual(buildFormFields({ type: "object" }), []);
}

export async function run() {
  _testBuildFormFieldsMapsSchemaAndHints();
  _testBuildFormFieldsHandlesInvalidSchema();
}

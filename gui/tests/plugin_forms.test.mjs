import assert from "node:assert/strict";

import { buildFormFields, orderFieldsByLayout, resolveFieldStep } from "../lib/plugin_forms.mjs";

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
        fine_step: 0.1,
      },
    },
    {
      json_pointer: "/properties/mode/x_mmo_ui",
      hint: {
        widget: "selector",
        options: [
          { value: "strict", label: "Strict" },
          { value: "safe", label: "Safe" },
        ],
      },
    },
  ];

  const fields = buildFormFields(schema, uiHints);
  assert.equal(fields.length, 4);

  const byName = new Map(fields.map((field) => [field.name, field]));
  assert.equal(byName.get("threshold_db").inputKind, "range");
  assert.equal(byName.get("threshold_db").textEntry, true);
  assert.equal(byName.get("threshold_db").required, true);
  assert.equal(byName.get("threshold_db").step, 0.5);
  assert.equal(byName.get("threshold_db").fineStep, 0.1);
  assert.equal(byName.get("threshold_db").hint.widget, "fader");
  assert.equal(byName.get("threshold_db").units, "dB");

  assert.equal(byName.get("enabled").inputKind, "checkbox");
  assert.equal(byName.get("enabled").required, true);

  assert.equal(byName.get("mode").inputKind, "select");
  assert.deepEqual(byName.get("mode").enumValues, ["safe", "strict"]);
  assert.deepEqual(
    byName.get("mode").selectOptions,
    [
      { value: "strict", label: "Strict" },
      { value: "safe", label: "Safe" },
    ],
  );

  assert.equal(byName.get("comment").inputKind, "text");
  assert.equal(byName.get("comment").required, false);
}

function _testResolveFieldStepUsesFineStepModifier() {
  const field = {
    step: 1,
    fineStep: 0.25,
    modifierKey: "shift",
  };
  assert.equal(resolveFieldStep(field, { shift: false }), 1);
  assert.equal(resolveFieldStep(field, { shift: true }), 0.25);
  assert.equal(resolveFieldStep(field, { alt: true }), 1);
}

function _testSelectorFallsBackToEnumWhenOptionsMissing() {
  const schema = {
    type: "object",
    properties: {
      mode: {
        type: "string",
        enum: ["safe", "strict"],
      },
    },
  };
  const uiHints = [
    {
      json_pointer: "/properties/mode/x_mmo_ui",
      hint: {
        widget: "selector",
      },
    },
  ];

  const fields = buildFormFields(schema, uiHints);
  const modeField = fields.find((field) => field.name === "mode");
  assert.deepEqual(
    modeField?.selectOptions,
    [
      { value: "safe", label: "safe" },
      { value: "strict", label: "strict" },
    ],
  );
}

function _testOrderFieldsByLayoutUsesWidgetParamRefOrder() {
  const fields = [
    { name: "gain_v2" },
    { name: "gain_v0" },
    { name: "gain_v1" },
    { name: "trim_db" },
  ];
  const uiLayout = {
    sections: [
      {
        section_id: "main",
        widgets: [
          { widget_id: "gain_0", param_ref: "PARAM.RENDERER.GAIN_V0" },
          { widget_id: "gain_1", param_ref: "/properties/gain_v1" },
          { widget_id: "trim", param_ref: "trim_db" },
        ],
      },
    ],
  };

  const ordered = orderFieldsByLayout(fields, uiLayout);
  assert.equal(ordered.hasLayout, true);
  assert.deepEqual(
    ordered.orderedFields.map((field) => field.name),
    ["gain_v0", "gain_v1", "trim_db"],
  );
  assert.deepEqual(
    ordered.moreFields.map((field) => field.name),
    ["gain_v2"],
  );
}

function _testBuildFormFieldsHandlesInvalidSchema() {
  assert.deepEqual(buildFormFields(null), []);
  assert.deepEqual(buildFormFields([]), []);
  assert.deepEqual(buildFormFields({ type: "object" }), []);
}

export async function run() {
  _testBuildFormFieldsMapsSchemaAndHints();
  _testResolveFieldStepUsesFineStepModifier();
  _testSelectorFallsBackToEnumWhenOptionsMissing();
  _testOrderFieldsByLayoutUsesWidgetParamRefOrder();
  _testBuildFormFieldsHandlesInvalidSchema();
}

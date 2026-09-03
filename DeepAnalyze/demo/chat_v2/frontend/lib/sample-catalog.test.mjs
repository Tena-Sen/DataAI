import assert from "node:assert/strict";
import test from "node:test";
import {
  findSampleSelection,
  normalizeSampleCatalog,
} from "./sample-catalog.js";

const datasets = [
  {
    id: "penguins",
    files: ["penguins.csv"],
    questions: [{ id: "full" }, { id: "quick" }],
  },
];

test("normalizes only usable sample datasets", () => {
  assert.deepEqual(normalizeSampleCatalog({ datasets }), datasets);
  assert.deepEqual(
    normalizeSampleCatalog({ datasets: [...datasets, { id: "empty", files: [] }] }),
    datasets
  );
});

test("finds a valid dataset and question pair", () => {
  assert.equal(findSampleSelection(datasets, "penguins", "quick")?.question.id, "quick");
  assert.equal(findSampleSelection(datasets, "penguins", "missing"), null);
});

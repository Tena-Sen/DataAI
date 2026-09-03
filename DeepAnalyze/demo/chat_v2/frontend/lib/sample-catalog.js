function normalizeSampleCatalog(payload) {
  const datasets = Array.isArray(payload?.datasets) ? payload.datasets : [];
  return datasets.filter(
    (dataset) =>
      dataset &&
      typeof dataset.id === "string" &&
      Array.isArray(dataset.files) &&
      dataset.files.length > 0 &&
      Array.isArray(dataset.questions) &&
      dataset.questions.length > 0
  );
}

function findSampleSelection(datasets, datasetId, questionId) {
  const dataset = (Array.isArray(datasets) ? datasets : []).find(
    (item) => item.id === datasetId
  );
  if (!dataset) return null;
  const question = dataset.questions.find((item) => item.id === questionId);
  if (!question) return null;
  return { dataset, question };
}

module.exports = {
  findSampleSelection,
  normalizeSampleCatalog,
};

export interface SampleQuestionLike {
  id: string;
}

export interface SampleDatasetLike {
  id: string;
  files: string[];
  questions: SampleQuestionLike[];
}

export function normalizeSampleCatalog(payload: unknown): SampleDatasetLike[];
export function findSampleSelection(
  datasets: SampleDatasetLike[],
  datasetId: string,
  questionId: string
): { dataset: SampleDatasetLike; question: SampleQuestionLike } | null;

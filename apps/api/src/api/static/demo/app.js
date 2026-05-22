const MODES = {
  FT: 'ft',
  MODELS: 'models',
  RAG: 'rag',
};

const TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed']);
const ACTIVE_JOB_STATUSES = new Set(['queued', 'running']);
const ACTIVE_FT_JOB_STATUSES = new Set(['queued', 'preparing_data', 'training', 'packaging', 'registering', 'running']);
const FT_LIFECYCLE_STEPS = [
  {
    key: 'queued',
    label: 'Queued',
    description: 'The smoke or local training job has been accepted and is waiting for a worker slot.',
  },
  {
    key: 'running',
    label: 'Running',
    description: 'A worker has claimed the job and is about to advance the fine-tuning phases.',
  },
  {
    key: 'preparing_data',
    label: 'Preparing dataset',
    description: 'The locked dataset version is being exported and validated into a trainer-ready snapshot.',
  },
  {
    key: 'training',
    label: 'Training adapter',
    description: 'The local fine-tuning backend is running the configured SFT + LoRA training step.',
  },
  {
    key: 'packaging',
    label: 'Packaging artifacts',
    description: 'Adapter, report, log, and publish-manifest artifacts are being validated and recorded.',
  },
  {
    key: 'registering',
    label: 'Registering model',
    description: 'The validated artifact bundle is being recorded in the model registry for review-only inspection.',
  },
];
const SMOKE_BASE_MODEL_NAME = 'qwen3.5:4b';
const SMOKE_TRAINER_MODEL_NAME = 'hf-internal/testing-tiny-random-gpt2';
const SMOKE_HYPERPARAMETER_PRESET = {
  epochs: 1,
  learning_rate: 0.0005,
  batch_size: 1,
  gradient_accumulation_steps: 1,
  max_seq_length: 256,
  lora_r: 4,
  lora_alpha: 8,
  lora_dropout: 0.0,
  seed: 42,
  trainer_model_name: SMOKE_TRAINER_MODEL_NAME,
  smoke_test: true,
};
const SMOKE_DATASET_SEED_ROWS = [
  {
    instruction: 'Summarize the maintenance note',
    input: 'Pump 3 vibration increased after the filter swap. Inspect the bearings during the next shutdown.',
    output: 'Inspect Pump 3 bearings during the next shutdown because vibration increased after the filter swap.',
  },
  {
    instruction: 'Classify the maintenance urgency',
    input: 'Cooling fan alarm cleared after restart. Monitor during the next routine round.',
    output: 'monitor',
  },
  {
    instruction: 'Generate a reviewer action',
    input: 'Pressure drift exceeded the morning threshold on line 2 and calibration is overdue.',
    output: 'Schedule line 2 pressure-sensor calibration and review the morning threshold drift.',
  },
];

const state = {
  mode: MODES.FT,
  ft: {
    hasLoadedInitialData: false,
    datasets: [],
    selectedDatasetId: null,
    selectedDataset: null,
    selectedVersionId: null,
    selectedVersion: null,
    rows: [],
    selectedRowId: null,
    trainingJobs: [],
    selectedTrainingJobId: null,
    selectedTrainingJob: null,
    pollHandle: null,
    pollTrainingJobId: null,
    requestTokens: {
      dataset: 0,
      version: 0,
      trainingJob: 0,
    },
  },
  models: {
    hasLoadedInitialData: false,
    items: [],
    selectedReviewModelId: null,
    selectedReviewModel: null,
    selectedInferenceModelId: null,
    ragCollections: [],
    selectedRagCollectionId: '',
    inferenceResult: null,
    requestTokens: {
      detail: 0,
    },
  },
  rag: {
    hasLoadedInitialData: false,
    collections: [],
    selectedCollectionId: null,
    selectedCollection: null,
    documents: [],
    selectedDocumentId: null,
    selectedDocument: null,
    retrievalPreview: null,
    requestTokens: {
      collection: 0,
      document: 0,
    },
  },
};

const dom = {
  modeButtons: Array.from(document.querySelectorAll('[data-mode]')),
  ftMode: document.querySelector('#ft-mode'),
  modelsMode: document.querySelector('#models-mode'),
  ragMode: document.querySelector('#rag-mode'),
  ft: {
    datasetsRefresh: document.querySelector('#ft-datasets-refresh'),
    datasetName: document.querySelector('#ft-dataset-name'),
    datasetTaskType: document.querySelector('#ft-dataset-task-type'),
    datasetSchemaType: document.querySelector('#ft-dataset-schema-type'),
    datasetDescription: document.querySelector('#ft-dataset-description'),
    createDatasetButton: document.querySelector('#ft-create-dataset-button'),
    datasetHint: document.querySelector('#ft-dataset-hint'),
    datasetList: document.querySelector('#ft-dataset-list'),
    datasetDetail: document.querySelector('#ft-dataset-detail'),
    versionLabel: document.querySelector('#ft-version-label'),
    trainRatio: document.querySelector('#ft-train-ratio'),
    valRatio: document.querySelector('#ft-val-ratio'),
    testRatio: document.querySelector('#ft-test-ratio'),
    createVersionButton: document.querySelector('#ft-create-version-button'),
    versionList: document.querySelector('#ft-version-list'),
    versionDetail: document.querySelector('#ft-version-detail'),
    versionStatusSelect: document.querySelector('#ft-version-status-select'),
    applyVersionStatusButton: document.querySelector('#ft-apply-version-status-button'),
    versionRefresh: document.querySelector('#ft-version-refresh'),
    rowSplit: document.querySelector('#ft-row-split'),
    rowInputJson: document.querySelector('#ft-row-input-json'),
    rowTargetJson: document.querySelector('#ft-row-target-json'),
    rowMetadataJson: document.querySelector('#ft-row-metadata-json'),
    addRowButton: document.querySelector('#ft-add-row-button'),
    versionHint: document.querySelector('#ft-version-hint'),
    rowSummary: document.querySelector('#ft-row-summary'),
    rowList: document.querySelector('#ft-row-list'),
    rowDetail: document.querySelector('#ft-row-detail'),
    baseModelName: document.querySelector('#ft-base-model-name'),
    trainingMethod: document.querySelector('#ft-training-method'),
    trainingHyperparamsJson: document.querySelector('#ft-training-hyperparams-json'),
    enqueueTrainingButton: document.querySelector('#ft-enqueue-training-button'),
    trainingHint: document.querySelector('#ft-training-hint'),
    fillSmokePresetButton: document.querySelector('#ft-fill-smoke-preset-button'),
    prepareSmokeDatasetButton: document.querySelector('#ft-prepare-smoke-dataset-button'),
    enqueueSmokeTrainingButton: document.querySelector('#ft-enqueue-smoke-training-button'),
    trainingRefresh: document.querySelector('#ft-training-refresh'),
    trainingList: document.querySelector('#ft-training-list'),
    trainingDetail: document.querySelector('#ft-training-detail'),
  },
  models: {
    refresh: document.querySelector('#models-refresh'),
    list: document.querySelector('#models-list'),
    detail: document.querySelector('#model-detail'),
    statusSummary: document.querySelector('#models-status-summary'),
    inferenceSummary: document.querySelector('#inference-selection-summary'),
    modelSelect: document.querySelector('#inference-model-select'),
    ragCollectionSelect: document.querySelector('#inference-rag-collection-select'),
    temperature: document.querySelector('#inference-temperature'),
    maxTokens: document.querySelector('#inference-max-tokens'),
    topK: document.querySelector('#inference-top-k'),
    prompt: document.querySelector('#inference-prompt'),
    runButton: document.querySelector('#inference-run-button'),
    runHint: document.querySelector('#inference-run-hint'),
    result: document.querySelector('#inference-result'),
  },
  rag: {
    collectionsRefresh: document.querySelector('#rag-collections-refresh'),
    collectionName: document.querySelector('#rag-collection-name'),
    collectionDescription: document.querySelector('#rag-collection-description'),
    embeddingModel: document.querySelector('#rag-embedding-model'),
    chunkingPolicyJson: document.querySelector('#rag-chunking-policy-json'),
    createCollectionButton: document.querySelector('#rag-create-collection-button'),
    collectionHint: document.querySelector('#rag-collection-hint'),
    collectionList: document.querySelector('#rag-collection-list'),
    collectionDetail: document.querySelector('#rag-collection-detail'),
    documentsRefresh: document.querySelector('#rag-documents-refresh'),
    documentSourceType: document.querySelector('#rag-document-source-type'),
    documentFile: document.querySelector('#rag-document-file'),
    uploadDocumentButton: document.querySelector('#rag-upload-document-button'),
    documentHint: document.querySelector('#rag-document-hint'),
    documentSummary: document.querySelector('#rag-document-summary'),
    documentList: document.querySelector('#rag-document-list'),
    documentDetail: document.querySelector('#rag-document-detail'),
    previewQuery: document.querySelector('#rag-preview-query'),
    previewTopK: document.querySelector('#rag-preview-top-k'),
    previewButton: document.querySelector('#rag-preview-button'),
    previewHint: document.querySelector('#rag-preview-hint'),
    previewResult: document.querySelector('#rag-preview-result'),
  },
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || `Request failed: ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function buildUrl(path, params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') {
      search.set(key, value);
    }
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatJson(value) {
  return escapeHtml(JSON.stringify(value, null, 2));
}

function formatDateTime(value) {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? escapeHtml(value) : parsed.toLocaleString();
}

function renderBadge(label) {
  return `<span class="tag">${escapeHtml(label)}</span>`;
}

function statusClassFor(status) {
  if (status === 'passed' || status === 'succeeded') {
    return 'is-success';
  }
  if (status === 'pass') {
    return 'is-success';
  }
  if (status === 'failed') {
    return 'is-failed';
  }
  if (status === 'fail') {
    return 'is-failed';
  }
  if (status === 'error') {
    return 'is-error';
  }
  if (status === 'running') {
    return 'is-running';
  }
  if (status === 'preparing_data' || status === 'training' || status === 'packaging' || status === 'registering') {
    return 'is-running';
  }
  if (status === 'queued') {
    return 'is-queued';
  }
  return '';
}

function renderStatusBadge(status) {
  return `<span class="status-badge ${statusClassFor(status)}">${escapeHtml(status || 'unknown')}</span>`;
}

function renderDetailGrid(rows) {
  return `
    <dl class="detail-grid">
      ${rows
        .map(
          ({ label, value }) => `
            <div>
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(value ?? '—')}</dd>
            </div>
          `,
        )
        .join('')}
    </dl>
  `;
}

function renderJsonCallout(title, value) {
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">${escapeHtml(title)}</h4>
      <pre class="json-block">${formatJson(value)}</pre>
    </section>
  `;
}

function normalizeSearchValue(value) {
  return String(value || '').trim().toLowerCase();
}

function matchesTextFilter(parts, query) {
  const normalizedQuery = normalizeSearchValue(query);
  if (!normalizedQuery) {
    return true;
  }
  return parts.some((part) => normalizeSearchValue(part).includes(normalizedQuery));
}

function countLabel(value, noun) {
  return `${value} ${noun}${value === 1 ? '' : 's'}`;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === '[object Object]';
}

function uniqueSortedValues(values) {
  return Array.from(new Set(safeArray(values).filter(Boolean).map((value) => String(value).trim()).filter(Boolean))).sort((left, right) =>
    left.localeCompare(right),
  );
}

function parseOptionalJsonValue(rawValue, { allowStringFallback = true, fallbackValue = null, requireObject = false, fieldLabel = 'value' } = {}) {
  const trimmed = String(rawValue || '').trim();
  if (!trimmed) {
    return fallbackValue;
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (requireObject && !isPlainObject(parsed)) {
      throw new Error(`${fieldLabel} must be a JSON object.`);
    }
    return parsed;
  } catch (error) {
    if (error instanceof Error && error.message.endsWith('must be a JSON object.')) {
      throw error;
    }
    if (requireObject || !allowStringFallback) {
      throw new Error(`${fieldLabel} must be valid JSON.`);
    }
    return trimmed;
  }
}

function parseNumberInput(rawValue, { fallback = null, minimum = null, fieldLabel = 'value', integer = false } = {}) {
  const trimmed = String(rawValue ?? '').trim();
  if (!trimmed) {
    return fallback;
  }
  const parsed = integer ? Number.parseInt(trimmed, 10) : Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${fieldLabel} must be a valid number.`);
  }
  if (minimum !== null && parsed < minimum) {
    throw new Error(`${fieldLabel} must be at least ${minimum}.`);
  }
  return parsed;
}

function populateSelectOptions(select, options, { placeholderLabel, selectedValue } = {}) {
  if (!select) {
    return;
  }
  const fragments = [];
  if (placeholderLabel) {
    fragments.push(`<option value="">${escapeHtml(placeholderLabel)}</option>`);
  }
  fragments.push(
    options
      .map(
        (option) =>
          `<option value="${escapeHtml(option)}" ${String(option) === String(selectedValue || '') ? 'selected' : ''}>${escapeHtml(option)}</option>`,
      )
      .join(''),
  );
  select.innerHTML = fragments.join('');
}

function populateMappedSelectOptions(select, items, { placeholderLabel, selectedValue, valueKey = 'id', labelBuilder = null } = {}) {
  if (!select) {
    return;
  }
  const fragments = [];
  if (placeholderLabel) {
    fragments.push(`<option value="">${escapeHtml(placeholderLabel)}</option>`);
  }
  fragments.push(
    safeArray(items)
      .map((item) => {
        const value = item?.[valueKey] ?? '';
        const label = labelBuilder ? labelBuilder(item) : value;
        return `<option value="${escapeHtml(value)}" ${String(value) === String(selectedValue || '') ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      })
      .join(''),
  );
  select.innerHTML = fragments.join('');
}

function renderJsonDetails(title, value, { open = false, summaryDetail = '' } = {}) {
  return `
    <details class="json-details" ${open ? 'open' : ''}>
      <summary>
        <span>${escapeHtml(title)}</span>
        ${summaryDetail ? `<span class="meta-line">${escapeHtml(summaryDetail)}</span>` : ''}
      </summary>
      <pre class="json-block">${formatJson(value)}</pre>
    </details>
  `;
}

function renderTextLog(title, value) {
  const lines = String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line, index, items) => line || items.length === 1 || index < items.length - 1);
  if (!lines.length) {
    return '';
  }
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">${escapeHtml(title)}</h4>
      <ol class="log-line-list">
        ${lines.map((line) => `<li>${escapeHtml(line || ' ')}</li>`).join('')}
      </ol>
    </section>
  `;
}

function hasRunProblems(run) {
  const summary = run.summary || {};
  return run.status === 'failed' || Number(summary.failed_count || 0) > 0 || Number(summary.error_count || 0) > 0;
}

function hasRunItemProblems(item) {
  return item.status === 'failed' || item.status === 'error';
}

function renderDetailList(title, items, tone = '') {
  if (!items.length) {
    return '';
  }
  return `
    <section class="callout ${escapeHtml(tone)}">
      <p class="callout-title">${escapeHtml(title)}</p>
      <div class="detail-stack">
        ${items.map((item) => `<p>${escapeHtml(item)}</p>`).join('')}
      </div>
    </section>
  `;
}

function renderComparisonSection(title, value) {
  return `
    <section class="comparison-card">
      <h4 class="subsection-title">${escapeHtml(title)}</h4>
      <pre class="json-block">${formatJson(value)}</pre>
    </section>
  `;
}

function renderIoLogList(logs) {
  const orderedLogs = safeArray(logs).slice().sort((left, right) => Number(left.sequence_no || 0) - Number(right.sequence_no || 0));
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">Execution I/O timeline</h4>
      <div class="io-log-list">
        ${orderedLogs
          .map(
            (log) => `
              <article class="io-log-card io-log-timeline-card">
                <div class="inline-meta">
                  ${renderStatusBadge(log.direction || 'unknown')}
                  ${renderBadge(`sequence ${log.sequence_no ?? 0}`)}
                  ${log.raw_type ? renderBadge(log.raw_type) : ''}
                </div>
                <p class="meta-line">${escapeHtml(log.memory_symbol || 'unmapped symbol')} · ${escapeHtml(log.memory_address || 'address n/a')} · recorded ${escapeHtml(formatDateTime(log.recorded_at))}</p>
                ${renderDetailGrid([
                  { label: 'Direction', value: log.direction || '—' },
                  { label: 'Memory symbol', value: log.memory_symbol || '—' },
                  { label: 'Memory address', value: log.memory_address || '—' },
                  { label: 'Recorded', value: formatDateTime(log.recorded_at) },
                ])}
                <section class="detail-stack compact-stack">
                  <h5 class="callout-title">Value</h5>
                  <pre class="json-block io-value-block">${formatJson(log.value_json)}</pre>
                </section>
              </article>
            `,
          )
          .join('')}
      </div>
    </section>
  `;
}

function renderRunLifecycle(status) {
  const currentStatus = status || 'queued';
  const steps = [
    { key: 'queued', label: 'Queued', description: 'Run accepted and waiting on the queue.' },
    { key: 'running', label: 'Running', description: 'Worker is executing testcase items.' },
    { key: 'succeeded', label: 'Succeeded', description: 'Run completed and results are ready to review.' },
    { key: 'failed', label: 'Failed', description: 'Job failed before the full result set completed.' },
  ];
  const activeIndex = steps.findIndex((step) => step.key === currentStatus);
  return steps
    .map((step, index) => {
      const classes = ['flow-step'];
      if (index < activeIndex || (currentStatus === 'succeeded' && index < 3) || (currentStatus === 'failed' && index < 2)) {
        classes.push('is-complete');
      }
      if (step.key === currentStatus) {
        classes.push('is-active', statusClassFor(step.key));
      }
      return `
        <article class="${classes.join(' ')}">
          <p class="stat-label">${escapeHtml(step.label)}</p>
          <p class="detail-copy">${escapeHtml(step.description)}</p>
        </article>
      `;
    })
    .join('');
}

function selectedFtDataset() {
  return state.ft.selectedDataset;
}

function selectedFtVersion() {
  return state.ft.selectedVersion;
}

function selectedFtRow() {
  return state.ft.rows.find((row) => String(row.id) === String(state.ft.selectedRowId)) || null;
}

function selectedFtTrainingJob() {
  return state.ft.selectedTrainingJob;
}

function selectedReviewModel() {
  if (!state.models.selectedReviewModelId) {
    return null;
  }
  if (state.models.selectedReviewModel?.id === state.models.selectedReviewModelId) {
    return state.models.selectedReviewModel;
  }
  return state.models.items.find((model) => model.id === state.models.selectedReviewModelId) || null;
}

function selectedInferenceModel() {
  return state.models.items.find((model) => model.id === state.models.selectedInferenceModelId) || null;
}

function selectedModelsRagCollection() {
  return state.models.ragCollections.find((collection) => collection.id === state.models.selectedRagCollectionId) || null;
}

function modelDisplayName(model) {
  return model?.display_name || model?.serving_model_name || model?.id || 'unknown model';
}

function modelRegistrySubtitle(model) {
  return model?.serving_model_name || model?.candidate_published_model_name || model?.base_model_name || 'model name unavailable';
}

function modelInferenceBlockedReason(model) {
  return model?.readiness?.selectable_reason
    || model?.readiness?.runtime_ready_reason
    || ((model?.artifact_id || model?.status === 'artifact_ready') && !model?.serving_model_name
      ? 'Adapter artifact only — no serving model yet.'
      : 'This model is not selectable for inference yet.');
}

function modelInferenceActionState(model) {
  if (model?.readiness?.selectable) {
    if (model.id === state.models.selectedInferenceModelId) {
      return {
        disabled: true,
        label: 'Already used for inference',
        reason: 'This model is already selected for inference.',
      };
    }
    return {
      disabled: false,
      label: 'Use for inference',
      reason: 'This updates only the inference model, selector, and runtime summary.',
    };
  }
  return {
    disabled: true,
    label: 'Use for inference',
    reason: modelInferenceBlockedReason(model),
  };
}

function modelCardActionCopy(model, inferenceAction) {
  const reviewCopy = model.id === state.models.selectedReviewModelId
    ? 'Review details is currently open.'
    : 'Review details updates only the review selection and detail panel.';
  return `${reviewCopy} ${inferenceAction.reason}`;
}

function smokeNameSuffix() {
  return new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14);
}

function buildSmokeDatasetRows() {
  return SMOKE_DATASET_SEED_ROWS.map((entry, index, items) => ({
    split: index === items.length - 1 ? 'val' : 'train',
    input_json: {
      instruction: entry.instruction,
      input: entry.input,
    },
    target_json: {
      output: entry.output,
    },
    metadata_json: {
      source: 'demo-ui-smoke-dataset',
      smoke_test: true,
      example_index: index + 1,
    },
  }));
}

function fillSmokeHyperparameterPreset() {
  dom.ft.trainingHyperparamsJson.value = JSON.stringify(SMOKE_HYPERPARAMETER_PRESET, null, 2);
  setFtTrainingHint(`Filled the smoke-test hyperparameter preset for ${SMOKE_TRAINER_MODEL_NAME}. Run preflight first before enqueueing a new runtime, keep Apple Silicon MPS on a host worker, make CPU fallback an explicit opt-in, and do not expect Ollama model publishing from the smoke job.`);
}

function applySmokeTrainingDefaults() {
  dom.ft.baseModelName.value = SMOKE_BASE_MODEL_NAME;
  dom.ft.trainingMethod.value = 'sft_qlora';
  dom.ft.trainingHyperparamsJson.value = JSON.stringify(SMOKE_HYPERPARAMETER_PRESET, null, 2);
}

function setModelsInferenceModel(modelId) {
  const nextModel = state.models.items.find((item) => item.id === modelId && item.readiness?.selectable) || null;
  state.models.selectedInferenceModelId = nextModel?.id || null;
  renderModelsRegistry();
  renderModelsStatus();
  renderModelDetail();
}

function selectedRagCollection() {
  return state.rag.selectedCollection;
}

function selectedRagDocument() {
  return state.rag.selectedDocument;
}

function setFtDatasetHint(message) {
  dom.ft.datasetHint.textContent = message || '';
}

function setFtVersionHint(message) {
  dom.ft.versionHint.textContent = message || '';
}

function setFtTrainingHint(message) {
  dom.ft.trainingHint.textContent = message || '';
}

function setModelsHint(message) {
  dom.models.runHint.textContent = message || '';
}

function setRagCollectionHint(message) {
  dom.rag.collectionHint.textContent = message || '';
}

function setRagDocumentHint(message) {
  dom.rag.documentHint.textContent = message || '';
}

function setRagPreviewHint(message) {
  dom.rag.previewHint.textContent = message || '';
}

function stopFtTrainingPolling() {
  window.clearInterval(state.ft.pollHandle);
  state.ft.pollHandle = null;
  state.ft.pollTrainingJobId = null;
}

async function setMode(mode) {
  if (mode !== MODES.FT) {
    stopFtTrainingPolling();
  }
  state.mode = mode;
  renderMode();
  if (mode === MODES.FT) {
    await ensureFtInitialized();
    return;
  }
  if (mode === MODES.MODELS) {
    await ensureModelsInitialized();
    return;
  }
  if (mode === MODES.RAG) {
    await ensureRagInitialized();
  }
}

function renderMode() {
  dom.ftMode.hidden = state.mode !== MODES.FT;
  dom.modelsMode.hidden = state.mode !== MODES.MODELS;
  dom.ragMode.hidden = state.mode !== MODES.RAG;
  dom.modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

async function activateDataset(datasetKey) {
  await fetchJson('/datasets/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_key: datasetKey }),
  });
  await refreshWorkflowSourcesAndModels();
}

function testcaseToNormalizationRow(testcase) {
  return {
    instruction_name: testcase.instruction_name,
    input_values: JSON.stringify([testcase.input_vector_json]),
    expected_outputs: JSON.stringify(
      Array.isArray(testcase.expected_outputs_json) && testcase.expected_outputs_json.length
        ? testcase.expected_outputs_json
        : [testcase.expected_output_json],
    ),
    input_type: testcase.input_type,
    output_type: testcase.output_type,
    description: testcase.description || '',
    tags: Array.isArray(testcase.tags) ? testcase.tags.join(',') : '',
    memory_profile_key: testcase.memory_profile_key || '',
    timeout_ms: testcase.timeout_ms,
    expected_outcome: testcase.expected_outcome,
  };
}

function renderFtDatasets() {
  if (!state.ft.datasets.length) {
    dom.ft.datasetList.className = 'stack-list empty';
    dom.ft.datasetList.textContent = 'Fine-tuning datasets will appear here.';
    return;
  }

  dom.ft.datasetList.className = 'stack-list';
  dom.ft.datasetList.innerHTML = state.ft.datasets
    .map((dataset) => {
      const currentVersion = safeArray(dataset.versions).find((version) => version.id === dataset.current_version_id) || safeArray(dataset.versions)[0] || null;
      return `
        <button type="button" class="list-card${dataset.id === state.ft.selectedDatasetId ? ' active' : ''}" data-ft-dataset-id="${escapeHtml(dataset.id)}">
          <div class="inline-meta">
            ${renderBadge(dataset.task_type || 'unknown task')}
            ${renderBadge(dataset.schema_type || 'unknown schema')}
            ${currentVersion ? renderStatusBadge(currentVersion.status) : renderBadge('no versions')}
          </div>
          <h3>${escapeHtml(dataset.name)}</h3>
          <p class="meta-line">${escapeHtml(dataset.id)} · ${countLabel(safeArray(dataset.versions).length, 'version')}</p>
          <div class="badge-row">
            ${dataset.current_version_id ? renderBadge(`current ${dataset.current_version_id}`) : renderBadge('no current version')}
            ${currentVersion ? renderBadge(`${currentVersion.row_summary?.total ?? currentVersion.row_count ?? 0} rows`) : ''}
          </div>
        </button>
      `;
    })
    .join('');

  dom.ft.datasetList.querySelectorAll('[data-ft-dataset-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadFtDataset(button.dataset.ftDatasetId);
    });
  });
}

function renderFtDatasetDetail() {
  const dataset = selectedFtDataset();
  if (!dataset) {
    dom.ft.datasetDetail.className = 'detail-stack empty';
    dom.ft.datasetDetail.textContent = 'Select a dataset to inspect versions and reviewer notes.';
    dom.ft.versionList.className = 'stack-list empty';
    dom.ft.versionList.textContent = 'Dataset versions will appear here after you select a dataset.';
    return;
  }

  dom.ft.datasetDetail.className = 'detail-stack';
  dom.ft.datasetDetail.innerHTML = `
    ${renderDetailGrid([
      { label: 'Dataset ID', value: dataset.id },
      { label: 'Name', value: dataset.name },
      { label: 'Task type', value: dataset.task_type },
      { label: 'Schema type', value: dataset.schema_type },
      { label: 'Current version', value: dataset.current_version_id || '—' },
      { label: 'Version count', value: safeArray(dataset.versions).length },
      { label: 'Created', value: formatDateTime(dataset.created_at) },
      { label: 'Updated', value: formatDateTime(dataset.updated_at) },
    ])}
    ${dataset.description ? `<section class="callout success"><p class="callout-title">Description</p><p>${escapeHtml(dataset.description)}</p></section>` : ''}
  `;

  const versions = safeArray(dataset.versions);
  if (!versions.length) {
    dom.ft.versionList.className = 'stack-list empty';
    dom.ft.versionList.textContent = 'Create a version to start adding rows and validating training data.';
    return;
  }

  dom.ft.versionList.className = 'stack-list';
  dom.ft.versionList.innerHTML = versions
    .map(
      (version) => `
        <button type="button" class="list-card${version.id === state.ft.selectedVersionId ? ' active' : ''}" data-ft-version-id="${escapeHtml(version.id)}">
          <div class="inline-meta">
            ${renderStatusBadge(version.status)}
            ${renderBadge(version.version_label || version.id)}
          </div>
          <h3>${escapeHtml(version.version_label || version.id)}</h3>
          <p class="meta-line">${escapeHtml(version.id)} · ${version.row_summary?.total ?? version.row_count ?? 0} rows</p>
          <div class="badge-row">
            ${renderBadge(`valid ${version.row_summary?.valid ?? 0}`)}
            ${renderBadge(`invalid ${version.row_summary?.invalid ?? 0}`)}
            ${renderBadge(`train ${version.train_split_ratio}`)}
          </div>
        </button>
      `,
    )
    .join('');

  dom.ft.versionList.querySelectorAll('[data-ft-version-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadFtVersion(button.dataset.ftVersionId);
    });
  });
}

function renderFtVersionDetail() {
  const version = selectedFtVersion();
  if (!version) {
    dom.ft.versionDetail.className = 'detail-stack empty';
    dom.ft.versionDetail.textContent = 'Select a dataset version to inspect row summary and training readiness.';
    dom.ft.versionStatusSelect.value = 'draft';
    renderFtSmokeActions();
    return;
  }

  dom.ft.versionStatusSelect.value = version.status || 'draft';
  const rowSummary = version.row_summary || {};
  const readinessTone = version.status === 'validated' || version.status === 'locked' ? 'success' : 'warning';
  const readinessCopy = version.status === 'draft'
    ? 'This version is still draft, so reviewers should inspect row validity before training can be enqueued successfully.'
    : version.status === 'validated'
      ? 'This version is validated and ready for training, while still allowing a final lock step if the reviewer wants to freeze it.'
      : 'This version is locked, which makes it training-ready and row-stable for repeatable review.';

  dom.ft.versionDetail.className = 'detail-stack';
  dom.ft.versionDetail.innerHTML = `
    <div class="inline-meta">${renderStatusBadge(version.status)}${renderBadge(version.version_label || version.id)}${renderBadge(`${rowSummary.total ?? version.row_count ?? 0} rows`)}</div>
    ${renderDetailGrid([
      { label: 'Version ID', value: version.id },
      { label: 'Dataset ID', value: version.dataset_id },
      { label: 'Version label', value: version.version_label },
      { label: 'Status', value: version.status },
      { label: 'Train split', value: version.train_split_ratio },
      { label: 'Validation split', value: version.val_split_ratio },
      { label: 'Test split', value: version.test_split_ratio },
      { label: 'Created', value: formatDateTime(version.created_at) },
      { label: 'Updated', value: formatDateTime(version.updated_at) },
    ])}
    <section class="callout ${readinessTone}">
      <p class="callout-title">Version readiness</p>
      <div class="badge-row">
        ${renderBadge(`total ${rowSummary.total ?? 0}`)}
        ${renderBadge(`valid ${rowSummary.valid ?? 0}`)}
        ${renderBadge(`invalid ${rowSummary.invalid ?? 0}`)}
      </div>
      <p>${escapeHtml(readinessCopy)}</p>
    </section>
    ${rowSummary.by_split ? renderJsonDetails('Row split summary', rowSummary.by_split, { summaryDetail: 'Rows grouped by split' }) : ''}
  `;
  renderFtSmokeActions();
}

function renderFtRows() {
  if (!selectedFtVersion()) {
    dom.ft.rowSummary.textContent = 'Version rows will appear here.';
    dom.ft.rowList.className = 'stack-list empty';
    dom.ft.rowList.textContent = 'Version rows will appear here.';
    return;
  }

  if (!state.ft.rows.length) {
    dom.ft.rowSummary.textContent = 'No rows have been added to this version yet.';
    dom.ft.rowList.className = 'stack-list empty';
    dom.ft.rowList.textContent = 'No rows have been added to this version yet.';
    return;
  }

  const validCount = state.ft.rows.filter((row) => row.validation_status === 'valid').length;
  const invalidCount = state.ft.rows.filter((row) => row.validation_status === 'invalid').length;
  dom.ft.rowSummary.textContent = `${countLabel(state.ft.rows.length, 'row')} · ${validCount} valid · ${invalidCount} invalid.`;
  dom.ft.rowList.className = 'stack-list';
  dom.ft.rowList.innerHTML = state.ft.rows
    .map((row) => `
      <button type="button" class="list-card${String(row.id) === String(state.ft.selectedRowId) ? ' active' : ''}" data-ft-row-id="${escapeHtml(row.id)}">
        <div class="inline-meta">
          ${renderStatusBadge(row.validation_status || 'pending')}
          ${renderBadge(row.split || 'unlabeled')}
          ${renderBadge(`row ${row.id}`)}
        </div>
        <h3>${escapeHtml(typeof row.input_json === 'string' ? row.input_json.slice(0, 48) || `Row ${row.id}` : `Row ${row.id}`)}</h3>
        <p class="meta-line">created ${escapeHtml(formatDateTime(row.created_at))}</p>
        ${row.validation_error ? `<p class="meta-line">${escapeHtml(row.validation_error)}</p>` : ''}
      </button>
    `)
    .join('');

  dom.ft.rowList.querySelectorAll('[data-ft-row-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.ft.selectedRowId = button.dataset.ftRowId;
      renderFtRows();
      renderFtRowDetail();
    });
  });
}

function renderFtRowDetail() {
  const row = selectedFtRow();
  if (!row) {
    dom.ft.rowDetail.className = 'detail-stack empty';
    dom.ft.rowDetail.textContent = 'Select a row to inspect its input, target, and validation state.';
    return;
  }

  dom.ft.rowDetail.className = 'detail-stack';
  dom.ft.rowDetail.innerHTML = `
    <div class="inline-meta">${renderStatusBadge(row.validation_status || 'pending')}${renderBadge(row.split || 'unlabeled')}${renderBadge(`row ${row.id}`)}</div>
    ${renderDetailGrid([
      { label: 'Row ID', value: row.id },
      { label: 'Version ID', value: row.dataset_version_id },
      { label: 'Split', value: row.split },
      { label: 'Validation status', value: row.validation_status },
      { label: 'Created', value: formatDateTime(row.created_at) },
      { label: 'Updated', value: formatDateTime(row.updated_at) },
    ])}
    ${row.validation_error ? `<section class="callout failure"><p class="callout-title">Validation error</p><p>${escapeHtml(row.validation_error)}</p></section>` : '<section class="callout success"><p class="callout-title">Validation</p><p>This row is currently valid for the selected fine-tuning task.</p></section>'}
    ${renderJsonCallout('Input payload', row.input_json)}
    ${renderJsonCallout('Target payload', row.target_json)}
    ${renderJsonCallout('Metadata payload', row.metadata_json || {})}
  `;
}

function renderFtSmokeActions() {
  if (!dom.ft.enqueueSmokeTrainingButton) {
    return;
  }
  const version = selectedFtVersion();
  const isLockedVersion = Boolean(version && version.status === 'locked');
  dom.ft.enqueueSmokeTrainingButton.disabled = !isLockedVersion;
  dom.ft.enqueueSmokeTrainingButton.title = isLockedVersion
    ? 'Queue the tiny smoke training preset for the locked selected version.'
    : 'Select a locked dataset version before enqueueing smoke training.';
}

function ftLifecycleProgressKey(job) {
  const lifecycleKeys = new Set(FT_LIFECYCLE_STEPS.map((step) => step.key));
  if (job?.status === 'failed' && lifecycleKeys.has(job?.error_json?.phase)) {
    return job.error_json.phase;
  }
  return lifecycleKeys.has(job?.status) ? job.status : 'queued';
}

function classifyFtTrainingFailure(job) {
  const error = job?.error_json && typeof job.error_json === 'object' ? job.error_json : {};
  const rawError = String(error.raw_error || error.message || job?.log_text || '').trim();
  const phase = String(error.phase || 'training');
  const lowered = rawError.toLowerCase();
  if (error.category && error.user_message && error.remediation) {
    return {
      category: error.category,
      phase,
      summary: String(error.user_message),
      remediation: String(error.remediation),
      rawError,
    };
  }
  if (lowered.includes('rag index') || lowered.includes('rag.db')) {
    return {
      category: 'rag_unrelated_failure',
      phase,
      summary: 'Training failed because the worker reported a RAG/index problem. That is unrelated to fine-tuning artifacts.',
      remediation: 'Fix the retrieval/index issue first, then rerun the fine-tuning job.',
      rawError,
    };
  }
  if (lowered.includes('locked dataset version') || lowered.includes('dataset version must be validated or locked')) {
    return {
      category: 'dataset_version_not_locked',
      phase,
      summary: 'Training failed because the selected dataset version was not locked for real training.',
      remediation: 'Validate the dataset version, lock it, and queue the smoke job again.',
      rawError,
    };
  }
  if (lowered.includes('artifacts failed validation')) {
    return {
      category: 'artifact_validation_failed',
      phase,
      summary: 'Training failed during artifact validation. The trainer ran, but expected adapter files were missing or incomplete.',
      remediation: 'Inspect the artifact directory and retry after fixing the packaging or validation issue.',
      rawError,
    };
  }
  if (lowered.includes('smoke fallback failed')) {
    return {
      category: 'smoke_fallback_failed',
      phase,
      summary: 'Training failed after the smoke fallback trainer was attempted. The deterministic demo path could not finish artifact generation.',
      remediation: 'Inspect the fallback artifact directory, confirm deterministic smoke fallback is enabled, and retry the smoke job.',
      rawError,
    };
  }
  if (lowered.includes('mlx_lm.lora cli is required') || lowered.includes('mlx_lm.fuse cli is required') || lowered.includes('missing mlx training tools')) {
    return {
      category: 'dependency_missing',
      phase,
      summary: 'Training failed because required MLX training tooling is missing.',
      remediation: 'Install or update brew mlx-lm (`brew install mlx mlx-lm`) on the macOS host, then rerun preflight.',
      rawError,
    };
  }
  if (lowered.includes('mlx qlora training failed') || lowered.includes('mlx model fusion failed') || lowered.includes('adapter not found')) {
    return {
      category: 'mlx_subprocess_failed',
      phase,
      summary: 'Training failed inside the MLX subprocess. Open training.log for the captured mlx_lm.lora/mlx_lm.fuse error.',
      remediation: 'Inspect data/model_artifacts/<job_id>/training.log, fix the reported MLX issue, and retry.',
      rawError,
    };
  }
  if (lowered.includes('metal') && (lowered.includes('unavailable') || lowered.includes('not available'))) {
    return {
      category: 'metal_runtime_unavailable',
      phase,
      summary: 'Training failed because Apple Silicon Metal is unavailable in the current runtime.',
      remediation: 'Rerun ./scripts/ft_smoke_preflight.sh from the macOS host shell and verify the brew-provided MLX runtime can access Metal.',
      rawError,
    };
  }
  if (lowered.includes('huggingface') || lowered.includes('from_pretrained') || lowered.includes('repositorynotfounderror') || lowered.includes("couldn't connect") || lowered.includes('401 client error') || lowered.includes('404 client error')) {
    return {
      category: 'hf_model_download_failure',
      phase,
      summary: 'Training failed while downloading the tiny trainer model. Check network access or use a locally cached trainer_model_name.',
      remediation: 'Verify connectivity or configure a locally available trainer model before retrying.',
      rawError,
    };
  }
  return {
    category: 'unknown',
    phase,
    summary: `Training failed during ${phase}. Review the technical details below for the captured training error.`,
    remediation: 'Check the raw error, confirm the Mac-native runtime, and retry after fixing the reported issue.',
    rawError,
  };
}

function renderFtFailureSummary(job) {
  const failure = classifyFtTrainingFailure(job);
  return `
    <section class="callout failure">
      <p class="callout-title">User-facing summary</p>
      <p>${escapeHtml(failure.summary)}</p>
      <div class="badge-row">${renderBadge(failure.category || 'unknown')}${renderBadge(`phase: ${failure.phase || 'training'}`)}</div>
      <p class="callout-title">What to do next</p>
      <p>${escapeHtml(failure.remediation)}</p>
      ${failure.rawError ? `<details><summary>Technical detail</summary><pre class="json-block">${escapeHtml(failure.rawError)}</pre></details>` : ''}
    </section>
  `;
}

function ftStatusNarrative(job) {
  const status = job?.status || 'queued';
  if (status === 'queued') {
    return {
      tone: 'warning',
      title: 'Queued for execution',
      body: 'The fine-tuning job is queued and waiting for a worker. Polling will keep the active job selected until it reaches a terminal state.',
    };
  }
  if (status === 'running') {
    return {
      tone: 'warning',
      title: 'Worker claimed the job',
      body: 'The worker is active and will advance into data preparation, training, packaging, and registration as the smoke run progresses.',
    };
  }
  if (status === 'preparing_data') {
    return {
      tone: 'warning',
      title: 'Preparing training snapshot',
      body: 'The selected locked version is being exported and validated before the trainer starts.',
    };
  }
  if (status === 'training') {
    return {
      tone: 'warning',
      title: 'Training in progress',
      body: 'The local trainer is actively producing adapter output from the locked dataset snapshot and smoke hyperparameters.',
    };
  }
  if (status === 'packaging') {
    return {
      tone: 'warning',
      title: 'Packaging and validation in progress',
      body: 'Adapter, report, log, and publish-manifest files are being validated before the registry entry is created.',
    };
  }
  if (status === 'registering') {
    return {
      tone: 'warning',
      title: 'Registering review artifact',
      body: 'The validated artifact package is being added to the Models registry while preserving artifact-only inference gating.',
    };
  }
  if (status === 'failed') {
    const failure = classifyFtTrainingFailure(job);
    return {
      tone: 'failure',
      title: 'Training failed',
      body: `${failure.summary} ${failure.remediation}`,
    };
  }
  if (job?.artifact_validation?.smoke_fallback_used) {
    return {
      tone: 'success',
      title: 'Training succeeded with smoke fallback',
      body: 'Smoke fallback trainer was used. This validates dataset/export/artifact/registry flow, not model quality. Use Mac MLX/QLoRA path for real trainer validation.',
    };
  }
  return {
    tone: 'success',
    title: 'Training succeeded',
    body: 'The smoke-training flow completed successfully. Review the validated artifact paths and use the review-only handoff to inspect the registered model in Models without changing inference selection.',
  };
}

function renderFtTrainingLifecycle(job) {
  const progressKey = ftLifecycleProgressKey(job);
  const activeIndex = FT_LIFECYCLE_STEPS.findIndex((step) => step.key === progressKey);
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">Training lifecycle</h4>
      <div class="run-lifecycle">
        ${FT_LIFECYCLE_STEPS.map((step, index) => {
          const classes = ['flow-step'];
          if (activeIndex > index || job.status === 'succeeded') {
            classes.push('is-complete');
          }
          if (step.key === progressKey && job.status !== 'succeeded') {
            classes.push('is-active', statusClassFor(job.status === 'failed' ? 'failed' : step.key));
          }
          return `
            <article class="${classes.join(' ')}">
              <p class="stat-label">${escapeHtml(step.label)}</p>
              <p class="detail-copy">${escapeHtml(step.description)}</p>
            </article>
          `;
        }).join('')}
      </div>
    </section>
  `;
}

function renderFtArtifactPathCards(artifactPaths) {
  const pathEntries = [
    ['Dataset export', artifactPaths.dataset_export_dir || '—'],
    ['Adapter directory', artifactPaths.adapter_dir || '—'],
    ['Training report', artifactPaths.training_report_path || '—'],
    ['Training log', artifactPaths.training_log_path || '—'],
    ['Publish manifest', artifactPaths.publish_manifest_path || '—'],
  ];
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">Artifact path summary</h4>
      <div class="ft-artifact-path-list">
        ${pathEntries
          .map(
            ([label, value]) => `
              <section class="callout ${value === '—' ? 'warning' : ''}">
                <p class="callout-title">${escapeHtml(label)}</p>
                <p class="ft-path-copy">${escapeHtml(value)}</p>
              </section>
            `,
          )
          .join('')}
      </div>
    </section>
  `;
}

function renderFtRegisteredModelCards(models) {
  const items = safeArray(models);
  if (!items.length) {
    return '';
  }
  return `
    <section class="detail-stack">
      <h4 class="subsection-title">Registered models</h4>
      <div class="ft-registered-model-list">
        ${items
          .map((model) => {
            const inferenceAction = modelInferenceActionState(model);
            return `
              <article class="ft-registered-model-card${model.readiness?.selectable ? '' : ' is-review-only'}">
                <div class="inline-meta">
                  ${renderStatusBadge(model.status || 'registered')}
                  ${renderBadge(model.publish_status || 'publish n/a')}
                  ${renderBadge(model.readiness?.selectable ? 'selectable' : 'artifact-only')}
                  ${renderBadge(model.readiness?.runtime_ready ? 'runtime-ready' : 'runtime-blocked')}
                </div>
                <h4>${escapeHtml(modelDisplayName(model))}</h4>
                <p class="meta-line">${escapeHtml(model.id || 'unknown model')} · ${escapeHtml(modelRegistrySubtitle(model))}</p>
                <p class="detail-copy">${escapeHtml(model.readiness?.selectable ? 'This model can be promoted separately for inference in Models.' : `${inferenceAction.reason} Use the review-only handoff to inspect it in Models without changing inference selection.`)}</p>
                <div class="button-row ft-review-handoff-row">
                  <button type="button" class="secondary-button" data-ft-review-model-id="${escapeHtml(model.id)}">Review in Models</button>
                </div>
              </article>
            `;
          })
          .join('')}
      </div>
    </section>
  `;
}

function renderFtTrainingJobs() {
  if (!state.ft.trainingJobs.length) {
    dom.ft.trainingList.className = 'stack-list empty';
    dom.ft.trainingList.textContent = 'Fine-tuning training jobs will appear here.';
    return;
  }

  dom.ft.trainingList.className = 'stack-list';
  dom.ft.trainingList.innerHTML = state.ft.trainingJobs
    .map((job) => `
      <button type="button" class="list-card${job.id === state.ft.selectedTrainingJobId ? ' active' : ''}" data-ft-training-job-id="${escapeHtml(job.id)}">
        <div class="inline-meta">
          ${renderStatusBadge(job.status)}
          ${renderBadge(job.base_model_name || 'base model n/a')}
        </div>
        <h3>${escapeHtml(job.dataset_name || job.dataset_version_label || job.id)}</h3>
        <p class="meta-line">${escapeHtml(job.id)} · version ${escapeHtml(job.dataset_version_id || '—')}</p>
        <div class="badge-row">
          ${renderBadge(job.training_method || 'training method n/a')}
          ${renderBadge(`${safeArray(job.artifacts).length} artifact${safeArray(job.artifacts).length === 1 ? '' : 's'}`)}
          ${renderBadge(`${safeArray(job.registered_models).length} registered model${safeArray(job.registered_models).length === 1 ? '' : 's'}`)}
        </div>
      </button>
    `)
    .join('');

  dom.ft.trainingList.querySelectorAll('[data-ft-training-job-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadFtTrainingJob(button.dataset.ftTrainingJobId);
    });
  });
}

function renderFtTrainingJobDetail() {
  const job = selectedFtTrainingJob();
  if (!job) {
    dom.ft.trainingDetail.className = 'detail-stack empty';
    dom.ft.trainingDetail.textContent = 'Select a training job to inspect artifacts and registered models.';
    return;
  }

  dom.ft.trainingDetail.className = 'detail-stack';
  const artifactValidation = job.artifact_validation || null;
  const publishReadiness = job.publish_readiness || null;
  const artifactPaths = job.artifact_paths || {};
  const statusNarrative = ftStatusNarrative(job);
  dom.ft.trainingDetail.innerHTML = `
    <div class="inline-meta">${renderStatusBadge(job.status)}${renderBadge(job.base_model_name || 'base model n/a')}${renderBadge(job.training_method || 'training')}</div>
    <section class="callout ${statusNarrative.tone}">
      <p class="callout-title">${escapeHtml(statusNarrative.title)}</p>
      <p>${escapeHtml(statusNarrative.body)}</p>
    </section>
    ${renderFtTrainingLifecycle(job)}
    ${renderDetailGrid([
      { label: 'Training job ID', value: job.id },
      { label: 'Dataset', value: job.dataset_name || '—' },
      { label: 'Dataset version', value: job.dataset_version_label || job.dataset_version_id || '—' },
      { label: 'Backing job ID', value: job.backing_job_id || '—' },
      { label: 'Serving/base model', value: job.base_model_name || '—' },
      { label: 'Trainer model', value: job.trainer_model_name || '—' },
      { label: 'Trainer backend', value: job.trainer_backend || '—' },
      { label: 'Device', value: job.device || '—' },
      { label: 'Training method', value: job.training_method || '—' },
      { label: 'Train rows', value: job.train_rows ?? '—' },
      { label: 'Validation rows', value: job.val_rows ?? '—' },
      { label: 'Test rows', value: job.test_rows ?? '—' },
      { label: 'Output directory', value: job.output_dir || '—' },
      { label: 'Created', value: formatDateTime(job.created_at) },
      { label: 'Started', value: formatDateTime(job.started_at) },
      { label: 'Finished', value: formatDateTime(job.finished_at) },
    ])}
    ${job.lineage_warning ? `<section class="callout warning"><p class="callout-title">Trainer/source mismatch</p><p>${escapeHtml(job.lineage_warning)}</p></section>` : ''}
    ${job.status === 'failed' ? renderFtFailureSummary(job) : ''}
    ${renderFtArtifactPathCards(artifactPaths)}
    ${artifactValidation ? `<section class="callout ${artifactValidation.artifact_valid ? 'success' : 'failure'}"><p class="callout-title">Artifact validation</p><div class="badge-row">${renderBadge(artifactValidation.artifact_valid ? 'validated' : 'invalid')}${renderBadge(job.artifact_paths?.adapter_dir ? 'adapter path ready' : 'adapter path missing')}${renderBadge(job.artifact_paths?.training_report_path ? 'report path ready' : 'report path missing')}${artifactValidation.smoke_fallback_used ? renderBadge('smoke fallback trainer used') : ''}</div><p>${escapeHtml(artifactValidation.artifact_valid ? 'Adapter/report/log artifacts passed structural validation before the job was marked succeeded.' : `Artifact validation failed: ${safeArray(artifactValidation.missing).join(', ') || 'unknown issue'}`)}</p>${safeArray(artifactValidation.warnings).length ? `<p>${safeArray(artifactValidation.warnings).map((warning) => escapeHtml(warning)).join(' ')}</p>` : ''}</section>` : ''}
    ${publishReadiness ? `<section class="callout ${publishReadiness.runtime_ready ? 'success' : 'warning'}"><p class="callout-title">Publish readiness</p><div class="badge-row">${renderBadge(publishReadiness.publish_status || 'publish n/a')}${renderBadge(publishReadiness.runtime_ready ? 'runtime-ready' : 'runtime-blocked')}${renderBadge(publishReadiness.candidate_published_model_name || 'candidate serving name pending')}</div><p>${escapeHtml(publishReadiness.runtime_ready ? 'A serving model is available for inference.' : publishReadiness.runtime_ready_reason || publishReadiness.selectable_reason || 'A serving model is not available yet.')}</p></section>` : ''}
    ${job.log_text ? `<section class="callout"><p class="callout-title">Training log</p><p>${escapeHtml(job.log_text)}</p></section>` : ''}
    ${renderFtRegisteredModelCards(job.registered_models)}
    ${renderJsonDetails('Training hyperparameters', job.hyperparams_json || {}, { summaryDetail: 'Submitted hyperparameter payload' })}
    ${renderJsonDetails('Artifact paths', artifactPaths, { summaryDetail: 'Adapter, report, log, and manifest locations' })}
    ${job.format_summary_json ? renderJsonDetails('Dataset formatting summary', job.format_summary_json, { summaryDetail: 'Prepared training snapshot' }) : ''}
    ${job.metrics_json ? renderJsonDetails('Training metrics', job.metrics_json, { summaryDetail: 'Captured trainer metrics' }) : ''}
    ${job.evaluation_json ? renderJsonDetails('Evaluation summary', job.evaluation_json, { summaryDetail: 'Current evaluation seam' }) : ''}
    ${job.error_json ? renderJsonDetails('Training error', job.error_json, { summaryDetail: 'Structured failure context' }) : ''}
    ${publishReadiness ? renderJsonDetails('Publish readiness payload', publishReadiness, { summaryDetail: 'Registry readiness and serving gate summary' }) : ''}
    ${safeArray(job.artifacts).length ? renderJsonDetails('Artifacts', job.artifacts, { summaryDetail: `${job.artifacts.length} persisted artifact entries` }) : ''}
    ${safeArray(job.registered_models).length ? renderJsonDetails('Registered models', job.registered_models, { summaryDetail: `${job.registered_models.length} model registry entries` }) : ''}
  `;

  dom.ft.trainingDetail.querySelectorAll('[data-ft-review-model-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await setMode(MODES.MODELS);
        await loadModelDetail(button.dataset.ftReviewModelId);
        setModelsHint('Opened the registered artifact in Models with a review-only handoff. Inference selection did not change.');
      } catch (error) {
        setFtTrainingHint(error.message);
      }
    });
  });
}

function clearFtSelections() {
  state.ft.selectedDatasetId = null;
  state.ft.selectedDataset = null;
  state.ft.selectedVersionId = null;
  state.ft.selectedVersion = null;
  state.ft.rows = [];
  state.ft.selectedRowId = null;
  renderFtDatasets();
  renderFtDatasetDetail();
  renderFtVersionDetail();
  renderFtRows();
  renderFtRowDetail();
}

async function refreshFtDatasets({ preferredDatasetId = null, preferredVersionId = null } = {}) {
  state.ft.datasets = await fetchJson('/ft-datasets');
  const nextDatasetId = preferredDatasetId && state.ft.datasets.some((dataset) => dataset.id === preferredDatasetId)
    ? preferredDatasetId
    : state.ft.datasets.some((dataset) => dataset.id === state.ft.selectedDatasetId)
      ? state.ft.selectedDatasetId
      : state.ft.datasets[0]?.id || null;
  state.ft.selectedDatasetId = nextDatasetId;
  renderFtDatasets();

  if (!nextDatasetId) {
    clearFtSelections();
    return;
  }

  await loadFtDataset(nextDatasetId, { preferredVersionId });
}

async function loadFtDataset(datasetId, { preferredVersionId = null, preserveRow = false } = {}) {
  if (!datasetId) {
    clearFtSelections();
    return;
  }

  const requestToken = ++state.ft.requestTokens.dataset;
  const dataset = await fetchJson(`/ft-datasets/${encodeURIComponent(datasetId)}`);
  if (requestToken !== state.ft.requestTokens.dataset) {
    return;
  }

  state.ft.selectedDatasetId = datasetId;
  state.ft.selectedDataset = dataset;
  const versions = safeArray(dataset.versions);
  state.ft.selectedVersionId = preferredVersionId && versions.some((version) => version.id === preferredVersionId)
    ? preferredVersionId
    : versions.some((version) => version.id === state.ft.selectedVersionId)
      ? state.ft.selectedVersionId
      : dataset.current_version_id && versions.some((version) => version.id === dataset.current_version_id)
        ? dataset.current_version_id
        : versions[0]?.id || null;

  renderFtDatasets();
  renderFtDatasetDetail();

  if (!state.ft.selectedVersionId) {
    state.ft.selectedVersion = null;
    state.ft.rows = [];
    state.ft.selectedRowId = null;
    renderFtVersionDetail();
    renderFtRows();
    renderFtRowDetail();
    return;
  }

  await loadFtVersion(state.ft.selectedVersionId, { preserveRow });
}

async function loadFtVersion(versionId, { preserveRow = false } = {}) {
  if (!versionId) {
    state.ft.selectedVersionId = null;
    state.ft.selectedVersion = null;
    state.ft.rows = [];
    state.ft.selectedRowId = null;
    renderFtDatasetDetail();
    renderFtVersionDetail();
    renderFtRows();
    renderFtRowDetail();
    return;
  }

  const requestToken = ++state.ft.requestTokens.version;
  const [version, rows] = await Promise.all([
    fetchJson(`/ft-dataset-versions/${encodeURIComponent(versionId)}`),
    fetchJson(`/ft-dataset-versions/${encodeURIComponent(versionId)}/rows`),
  ]);
  if (requestToken !== state.ft.requestTokens.version) {
    return;
  }

  state.ft.selectedVersionId = versionId;
  state.ft.selectedVersion = version;
  state.ft.rows = Array.isArray(rows) ? rows : [];
  if (state.ft.selectedDataset) {
    state.ft.selectedDataset.versions = safeArray(state.ft.selectedDataset.versions).map((item) => (item.id === version.id ? version : item));
  }
  if (!preserveRow || !state.ft.rows.some((row) => String(row.id) === String(state.ft.selectedRowId))) {
    state.ft.selectedRowId = state.ft.rows[0]?.id || null;
  }

  renderFtDatasetDetail();
  renderFtVersionDetail();
  renderFtRows();
  renderFtRowDetail();
}

function beginFtTrainingPolling(trainingJobId) {
  if (!trainingJobId) {
    stopFtTrainingPolling();
    return;
  }
  if (state.ft.pollTrainingJobId === trainingJobId && state.ft.pollHandle) {
    return;
  }

  stopFtTrainingPolling();
  state.ft.pollTrainingJobId = trainingJobId;
  state.ft.pollHandle = window.setInterval(async () => {
    try {
      const [trainingJob, trainingJobs] = await Promise.all([
        fetchJson(`/ft-training-jobs/${encodeURIComponent(trainingJobId)}`),
        fetchJson('/ft-training-jobs'),
      ]);
      state.ft.trainingJobs = Array.isArray(trainingJobs) ? trainingJobs : [];
      state.ft.selectedTrainingJobId = trainingJob.id;
      state.ft.selectedTrainingJob = trainingJob;
      renderFtTrainingJobs();
      renderFtTrainingJobDetail();

      if (TERMINAL_JOB_STATUSES.has(trainingJob.status)) {
        stopFtTrainingPolling();
        dom.ft.enqueueTrainingButton.disabled = false;
        if (dom.ft.enqueueSmokeTrainingButton) {
          renderFtSmokeActions();
        }
        setFtTrainingHint(
          trainingJob.status === 'succeeded'
            ? `Training job ${trainingJob.id} completed. Review the artifact paths below or use the review-only handoff to Models.`
            : classifyFtTrainingFailure(trainingJob).summary,
        );
      }
    } catch (error) {
      stopFtTrainingPolling();
      dom.ft.enqueueTrainingButton.disabled = false;
      if (dom.ft.enqueueSmokeTrainingButton) {
        renderFtSmokeActions();
      }
      setFtTrainingHint(error.message);
    }
  }, 1500);
}

async function enqueueFtTrainingJob({ version, baseModelName, trainingMethod, hyperparamsJson, queuedHint }) {
  const created = await fetchJson('/ft-training-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset_version_id: version.id,
      base_model_name: baseModelName,
      training_method: trainingMethod,
      hyperparams_json: hyperparamsJson,
    }),
  });
  await refreshFtTrainingJobs({ preferredTrainingJobId: created.id });
  beginFtTrainingPolling(created.id);
  setFtTrainingHint(queuedHint || `Training job ${created.id} queued for ${version.version_label || version.id}. Polling the active job now.`);
  return created;
}

function preferredFtTrainingJobId(trainingJobs, preferredTrainingJobId = null) {
  if (preferredTrainingJobId && trainingJobs.some((job) => job.id === preferredTrainingJobId)) {
    return preferredTrainingJobId;
  }

  if (state.ft.selectedTrainingJobId) {
    const activeSelectedJob = trainingJobs.find(
      (job) => job.id === state.ft.selectedTrainingJobId && ACTIVE_FT_JOB_STATUSES.has(job.status),
    );
    if (activeSelectedJob) {
      return activeSelectedJob.id;
    }
  }

  const newestActiveJob = trainingJobs.find((job) => ACTIVE_FT_JOB_STATUSES.has(job.status));
  if (newestActiveJob) {
    return newestActiveJob.id;
  }

  if (state.ft.selectedTrainingJobId && trainingJobs.some((job) => job.id === state.ft.selectedTrainingJobId)) {
    return state.ft.selectedTrainingJobId;
  }

  return trainingJobs[0]?.id || null;
}

async function refreshFtTrainingJobs({ preferredTrainingJobId = null } = {}) {
  state.ft.trainingJobs = await fetchJson('/ft-training-jobs');
  state.ft.selectedTrainingJobId = preferredFtTrainingJobId(state.ft.trainingJobs, preferredTrainingJobId);

  renderFtTrainingJobs();

  if (!state.ft.selectedTrainingJobId) {
    state.ft.selectedTrainingJob = null;
    stopFtTrainingPolling();
    renderFtTrainingJobDetail();
    return;
  }

  await loadFtTrainingJob(state.ft.selectedTrainingJobId);
}

async function loadFtTrainingJob(trainingJobId) {
  if (!trainingJobId) {
    state.ft.selectedTrainingJobId = null;
    state.ft.selectedTrainingJob = null;
    stopFtTrainingPolling();
    renderFtTrainingJobs();
    renderFtTrainingJobDetail();
    return;
  }

  const requestToken = ++state.ft.requestTokens.trainingJob;
  const trainingJob = await fetchJson(`/ft-training-jobs/${encodeURIComponent(trainingJobId)}`);
  if (requestToken !== state.ft.requestTokens.trainingJob) {
    return;
  }

  state.ft.selectedTrainingJobId = trainingJob.id;
  state.ft.selectedTrainingJob = trainingJob;
  if (ACTIVE_FT_JOB_STATUSES.has(trainingJob.status)) {
    beginFtTrainingPolling(trainingJob.id);
  } else {
    stopFtTrainingPolling();
  }
  renderFtTrainingJobs();
  renderFtTrainingJobDetail();
}

async function ensureFtInitialized({ force = false } = {}) {
  if (state.ft.hasLoadedInitialData && !force) {
    await refreshFtTrainingJobs({ preferredTrainingJobId: state.ft.selectedTrainingJobId });
    return;
  }

  await Promise.all([refreshFtDatasets(), refreshFtTrainingJobs()]);
  state.ft.hasLoadedInitialData = true;
}

function renderModelsRegistry() {
  const items = state.models.items;
  const selectableItems = items.filter((item) => item.readiness?.selectable);
  if (!items.length) {
    dom.models.list.className = 'stack-list empty';
    dom.models.list.textContent = 'Registered models will appear here.';
    populateMappedSelectOptions(dom.models.modelSelect, [], {
      placeholderLabel: 'No inference-selectable models available',
      selectedValue: '',
    });
    dom.models.modelSelect.disabled = true;
    renderModelsStatus();
    renderInferenceSelectionSummary();
    return;
  }

  dom.models.modelSelect.disabled = !selectableItems.length;
  populateMappedSelectOptions(dom.models.modelSelect, selectableItems, {
    placeholderLabel: selectableItems.length ? undefined : 'No inference-selectable models available',
    selectedValue: state.models.selectedInferenceModelId,
    valueKey: 'id',
    labelBuilder: (item) => `${modelDisplayName(item)} · ${item.status || 'unknown'} · ${item.publish_status || 'n/a'}`,
  });

  dom.models.list.className = 'stack-list';
  dom.models.list.innerHTML = items
    .map((model) => {
      const inferenceAction = modelInferenceActionState(model);
      return `
        <article class="list-card model-registry-card${model.id === state.models.selectedReviewModelId ? ' active' : ''}" data-model-card-id="${escapeHtml(model.id)}" tabindex="0" aria-label="Review model ${escapeHtml(modelDisplayName(model))}">
          <div class="inline-meta">
            ${renderStatusBadge(model.status || 'registered')}
            ${renderBadge(model.source_type || 'unknown source')}
            ${renderBadge(model.publish_status || 'publish n/a')}
            ${renderBadge(model.readiness?.selectable ? 'selectable' : 'artifact-only')}
            ${renderBadge(model.readiness?.runtime_ready ? 'runtime-ready' : 'runtime-blocked')}
            ${model.id === state.models.selectedReviewModelId ? renderBadge('reviewing model') : ''}
            ${model.id === state.models.selectedInferenceModelId ? renderBadge('inference model') : ''}
          </div>
          <h3>${escapeHtml(modelDisplayName(model))}</h3>
          <p class="meta-line">${escapeHtml(model.id)} · ${escapeHtml(modelRegistrySubtitle(model))}</p>
          <div class="badge-row">${safeArray(model.tags_json).map(renderBadge).join('')}</div>
          <div class="card-action-row">
            <button type="button" class="secondary-button" data-model-review-id="${escapeHtml(model.id)}">Review details</button>
            <button type="button" class="secondary-button" data-model-inference-id="${escapeHtml(model.id)}" ${inferenceAction.disabled ? 'disabled' : ''}>${escapeHtml(inferenceAction.label)}</button>
          </div>
          <p class="card-action-copy">${escapeHtml(modelCardActionCopy(model, inferenceAction))}</p>
        </article>
      `;
    })
    .join('');

  dom.models.list.querySelectorAll('[data-model-card-id]').forEach((card) => {
    const openReview = async () => {
      await loadModelDetail(card.dataset.modelCardId);
    };
    card.querySelectorAll('.card-action-row').forEach((actionRow) => {
      actionRow.addEventListener('click', (event) => {
        event.stopPropagation();
      });
    });
    card.addEventListener('click', async (event) => {
      const target = event.target;
      if (target instanceof Element && (target.closest('button') || target.closest('.card-action-row'))) {
        return;
      }
      await openReview();
    });
    card.addEventListener('keydown', async (event) => {
      if (event.target !== card) {
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        await openReview();
      }
    });
  });

  dom.models.list.querySelectorAll('[data-model-review-id]').forEach((button) => {
    button.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await loadModelDetail(button.dataset.modelReviewId);
    });
  });

  dom.models.list.querySelectorAll('[data-model-inference-id]').forEach((button) => {
    if (button.disabled) {
      return;
    }
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const nextModel = state.models.items.find((item) => item.id === button.dataset.modelInferenceId) || null;
      setModelsInferenceModel(button.dataset.modelInferenceId);
      setModelsHint(`Inference model set to ${modelDisplayName(nextModel)}.`);
    });
  });

  renderInferenceSelectionSummary();
}

function renderModelsStatus() {
  const reviewingModel = selectedReviewModel();
  const inferenceModel = selectedInferenceModel();
  const reviewCopy = reviewingModel
    ? `${modelDisplayName(reviewingModel)} is selected for review. Review details updates only selectedReviewModelId and the model detail panel.`
    : 'Choose a model from the registry to inspect readiness, lineage, and artifact detail.';
  const inferenceCopy = inferenceModel
    ? `${modelDisplayName(inferenceModel)} is the current inference model. Inference selection stays separate from the reviewing model and only includes runtime-ready/selectable models.`
    : 'No inference model is selected yet. Only runtime-ready/selectable models can run inference. Artifact-only models stay reviewable in the registry, but inference only uses models where readiness.selectable === true.';

  dom.models.statusSummary.innerHTML = `
    <section class="callout${reviewingModel ? '' : ' warning'}">
      <p class="callout-title">Reviewing model</p>
      <p>${escapeHtml(reviewCopy)}</p>
    </section>
    <section class="callout${inferenceModel ? ' success' : ' warning'}">
      <p class="callout-title">Inference model</p>
      <p>${escapeHtml(inferenceCopy)}</p>
    </section>
  `;
}

function renderModelsRagCollectionOptions() {
  populateMappedSelectOptions(dom.models.ragCollectionSelect, state.models.ragCollections, {
    placeholderLabel: 'No RAG collection',
    selectedValue: state.models.selectedRagCollectionId,
    valueKey: 'id',
    labelBuilder: (item) => `${item.name || item.id} · ${item.document_count ?? 0} docs`,
  });
  renderInferenceSelectionSummary();
}

function renderInferenceSelectionSummary() {
  const inferenceModel = selectedInferenceModel();
  const ragCollection = selectedModelsRagCollection();
  const ragState = ragCollection
    ? `${ragCollection.name || ragCollection.id} (${ragCollection.id}) · ${ragCollection.document_count ?? 0} docs`
    : 'none selected';

  if (!inferenceModel) {
    dom.models.inferenceSummary.className = 'detail-stack';
    dom.models.inferenceSummary.innerHTML = `
      <section class="callout warning">
        <p class="callout-title">Inference readiness</p>
        <p>Only runtime-ready/selectable models can run inference. Choose one in the selector or use a model card’s Use for inference action.</p>
      </section>
      ${renderDetailGrid([
        { label: 'Display name', value: '—' },
        { label: 'Model ID', value: '—' },
        { label: 'Serving model name', value: '—' },
        { label: 'Source type', value: '—' },
        { label: 'Publish status', value: '—' },
        { label: 'Runtime readiness', value: 'blocked — no inference model selected' },
        { label: 'Selected RAG collection', value: ragState },
      ])}
    `;
    return;
  }

  const readinessCopy = inferenceModel.readiness?.runtime_ready
    ? inferenceModel.readiness?.runtime_ready_reason || 'This model is runtime-ready for inference.'
    : modelInferenceBlockedReason(inferenceModel);

  dom.models.inferenceSummary.className = 'detail-stack';
  dom.models.inferenceSummary.innerHTML = `
    <section class="callout ${inferenceModel.readiness?.runtime_ready ? 'success' : 'warning'}">
      <p class="callout-title">Selected inference model</p>
      <div class="badge-row">
        ${renderBadge(inferenceModel.source_type || 'unknown source')}
        ${renderBadge(inferenceModel.publish_status || 'publish n/a')}
        ${renderBadge(inferenceModel.readiness?.selectable ? 'selectable' : 'not selectable')}
        ${renderBadge(inferenceModel.readiness?.runtime_ready ? 'runtime-ready' : 'runtime-blocked')}
      </div>
      <p>${escapeHtml(readinessCopy)}</p>
    </section>
    ${renderDetailGrid([
      { label: 'Display name', value: modelDisplayName(inferenceModel) },
      { label: 'Model ID', value: inferenceModel.id || '—' },
      { label: 'Serving model name', value: inferenceModel.serving_model_name || '—' },
      { label: 'Source type', value: inferenceModel.source_type || '—' },
      { label: 'Publish status', value: inferenceModel.publish_status || '—' },
      { label: 'Runtime readiness', value: inferenceModel.readiness?.runtime_ready ? 'ready' : `blocked — ${readinessCopy}` },
      { label: 'Selected RAG collection', value: ragState },
    ])}
  `;
}

function renderModelDetail() {
  const model = selectedReviewModel();
  if (!model) {
    dom.models.detail.className = 'detail-stack empty';
    dom.models.detail.textContent = 'Select a model to inspect registry metadata and artifact detail.';
    return;
  }

  const inferenceModel = selectedInferenceModel();
  const isInferenceModel = model.id === inferenceModel?.id;
  const isSelectableForInference = Boolean(model.readiness?.selectable);
  const inferenceAction = modelInferenceActionState(model);
  const inferenceAvailabilityCopy = isSelectableForInference
    ? isInferenceModel
      ? `${modelDisplayName(model)} is already the current inference model.`
      : `${modelDisplayName(model)} is selectable for inference. Promote it below when you want inference to use the model you are reviewing.`
    : `${modelInferenceBlockedReason(model)} Artifact-only models stay reviewable here, but inference only uses models with readiness.selectable === true.`;

  dom.models.detail.className = 'detail-stack';
  dom.models.detail.innerHTML = `
    <section class="callout">
      <p class="callout-title">Reviewing model</p>
      <p>${escapeHtml(`${modelDisplayName(model)} is selected in the registry detail panel. Review selection is separate from the inference model until you explicitly promote it.`)}</p>
    </section>
    <section class="callout ${isSelectableForInference ? 'success' : 'warning'}">
      <p class="callout-title">Inference availability</p>
      <p>${escapeHtml(inferenceAvailabilityCopy)}</p>
      <div class="button-row model-detail-actions"><button id="use-review-model-for-inference" type="button" class="secondary-button" ${inferenceAction.disabled ? 'disabled' : ''}>${escapeHtml(inferenceAction.label)}</button></div>
      <p class="card-action-copy">${escapeHtml(inferenceAction.reason)}</p>
    </section>
    <div class="inline-meta">${renderStatusBadge(model.status || 'registered')}${renderBadge(model.source_type || 'unknown source')}${renderBadge(model.publish_status || 'publish n/a')}${renderBadge(model.readiness?.selectable ? 'selectable' : 'artifact-only')}</div>
    ${renderDetailGrid([
      { label: 'Model ID', value: model.id || '—' },
      { label: 'Display name', value: model.display_name || '—' },
      { label: 'Source type', value: model.source_type || '—' },
      { label: 'Base lineage', value: model.base_model_name || '—' },
      { label: 'Trainer source', value: model.trainer_model_name || '—' },
      { label: 'Trainer backend', value: model.trainer_backend || '—' },
      { label: 'Artifact status', value: model.artifact_valid ? 'validated adapter artifact' : 'artifact validation pending' },
      { label: 'Published serving name', value: model.published_model_name || '—' },
      { label: 'Candidate serving name', value: model.candidate_published_model_name || '—' },
      { label: 'Serving model', value: model.serving_model_name || '—' },
      { label: 'Artifact ID', value: model.artifact_id || '—' },
      { label: 'Selectable', value: model.readiness?.selectable ? 'true' : 'false' },
      { label: 'Selectable reason', value: model.readiness?.selectable_reason || '—' },
      { label: 'Runtime ready', value: model.readiness?.runtime_ready ? 'true' : 'false' },
      { label: 'Runtime ready reason', value: model.readiness?.runtime_ready_reason || '—' },
      { label: 'Created', value: formatDateTime(model.created_at) },
      { label: 'Updated', value: formatDateTime(model.updated_at) },
    ])}
    ${safeArray(model.warnings).length ? `<section class="callout warning"><p class="callout-title">Model warnings</p><p>${safeArray(model.warnings).map((warning) => escapeHtml(warning)).join(' ')}</p></section>` : ''}
    ${safeArray(model.tags_json).length ? `<section class="callout"><p class="callout-title">Tags</p><div class="badge-row">${safeArray(model.tags_json).map(renderBadge).join('')}</div></section>` : ''}
    ${model.description ? `<section class="callout success"><p class="callout-title">Description</p><p>${escapeHtml(model.description)}</p></section>` : ''}
    ${model.lineage_json ? renderJsonDetails('Model lineage', model.lineage_json, { summaryDetail: 'Base lineage and training source' }) : ''}
    ${model.artifact ? renderJsonDetails('Artifact detail', model.artifact, { summaryDetail: 'Backing fine-tuning artifact' }) : ''}
  `;

  const useForInferenceButton = dom.models.detail.querySelector('#use-review-model-for-inference');
  if (useForInferenceButton && !useForInferenceButton.disabled) {
    useForInferenceButton.addEventListener('click', () => {
      setModelsInferenceModel(model.id);
      setModelsHint(`Inference model set to ${modelDisplayName(model)}.`);
    });
  }
}

function renderInferenceResult() {
  const result = state.models.inferenceResult;
  if (!result) {
    dom.models.result.className = 'detail-stack empty';
    dom.models.result.textContent = 'Inference answers, model metadata, and retrieval preview will appear here.';
    return;
  }

  const retrievalPreview = result.retrieval_preview || null;
  dom.models.result.className = 'detail-stack';
  dom.models.result.innerHTML = `
    <section class="callout success">
      <p class="callout-title">Inference answer</p>
      <p>${escapeHtml(result.answer || 'No answer returned.')}</p>
    </section>
    ${renderDetailGrid([
      { label: 'Inference model', value: result.model?.display_name || result.model?.serving_model_name || '—' },
      { label: 'Model ID', value: result.model?.id || '—' },
      { label: 'Model source', value: result.model?.source_type || '—' },
      { label: 'Base lineage', value: result.model?.base_model_name || '—' },
      { label: 'Publish status', value: result.model?.publish_status || '—' },
      { label: 'Runtime readiness', value: result.model?.readiness?.runtime_ready ? 'ready' : result.model?.readiness?.runtime_ready_reason || 'blocked' },
      { label: 'Provider', value: result.meta?.provider || '—' },
      { label: 'Serving model', value: result.meta?.model || '—' },
      { label: 'RAG collection', value: result.meta?.rag_collection_id || 'none' },
      { label: 'Temperature', value: result.meta?.temperature ?? '—' },
      { label: 'Max tokens', value: result.meta?.max_tokens ?? '—' },
    ])}
    ${renderJsonDetails('Inference model payload', result.model || {}, { summaryDetail: 'Resolved registry model used for the run' })}
    ${renderJsonDetails('Inference meta', result.meta || {}, { summaryDetail: 'Execution metadata returned by the API' })}
    ${retrievalPreview ? renderJsonDetails('Inference retrieval preview', retrievalPreview, { summaryDetail: `${safeArray(retrievalPreview.results).length} retrieval result${safeArray(retrievalPreview.results).length === 1 ? '' : 's'}` }) : '<section class="callout"><p class="callout-title">RAG context</p><p>No RAG collection was selected for this inference run.</p></section>'}
  `;
}

async function refreshModelsRegistry({ preferredReviewModelId = null, preferredInferenceModelId = null } = {}) {
  state.models.items = await fetchJson('/models');
  const reviewableIds = state.models.items.map((item) => item.id);
  const selectableIds = state.models.items.filter((item) => item.readiness?.selectable).map((item) => item.id);
  state.models.selectedReviewModelId = preferredReviewModelId && reviewableIds.includes(preferredReviewModelId)
    ? preferredReviewModelId
    : reviewableIds.includes(state.models.selectedReviewModelId)
      ? state.models.selectedReviewModelId
      : state.models.items[0]?.id || null;
  state.models.selectedInferenceModelId = preferredInferenceModelId && selectableIds.includes(preferredInferenceModelId)
    ? preferredInferenceModelId
    : selectableIds.includes(state.models.selectedInferenceModelId)
      ? state.models.selectedInferenceModelId
      : selectableIds[0] || null;
  state.models.selectedReviewModel = state.models.selectedReviewModelId
    ? state.models.items.find((item) => item.id === state.models.selectedReviewModelId) || null
    : null;

  renderModelsRegistry();
  renderModelsStatus();

  if (!state.models.selectedReviewModelId) {
    state.models.selectedReviewModel = null;
    renderModelDetail();
    return;
  }

  await loadModelDetail(state.models.selectedReviewModelId);
}

async function loadModelDetail(modelId) {
  if (!modelId) {
    state.models.selectedReviewModelId = null;
    state.models.selectedReviewModel = null;
    renderModelsRegistry();
    renderModelsStatus();
    renderModelDetail();
    return;
  }

  const requestToken = ++state.models.requestTokens.detail;
  const model = await fetchJson(`/models/${encodeURIComponent(modelId)}`);
  if (requestToken !== state.models.requestTokens.detail) {
    return;
  }

  state.models.selectedReviewModelId = model.id;
  state.models.selectedReviewModel = model;
  renderModelsRegistry();
  renderModelsStatus();
  renderModelDetail();
}

async function refreshModelsRagCollections() {
  state.models.ragCollections = await fetchJson('/rag-collections');
  if (state.models.selectedRagCollectionId && !state.models.ragCollections.some((collection) => collection.id === state.models.selectedRagCollectionId)) {
    state.models.selectedRagCollectionId = '';
  }
  renderModelsRagCollectionOptions();
}

async function ensureModelsInitialized({ force = false } = {}) {
  if (state.models.hasLoadedInitialData && !force) {
    return;
  }

  await Promise.all([refreshModelsRegistry(), refreshModelsRagCollections()]);
  renderInferenceResult();
  state.models.hasLoadedInitialData = true;
}

function renderRagCollections() {
  if (!state.rag.collections.length) {
    dom.rag.collectionList.className = 'stack-list empty';
    dom.rag.collectionList.textContent = 'RAG collections will appear here.';
    return;
  }

  dom.rag.collectionList.className = 'stack-list';
  dom.rag.collectionList.innerHTML = state.rag.collections
    .map((collection) => `
      <button type="button" class="list-card${collection.id === state.rag.selectedCollectionId ? ' active' : ''}" data-rag-collection-id="${escapeHtml(collection.id)}">
        <div class="inline-meta">
          ${renderStatusBadge(collection.index_status || 'ready')}
          ${renderBadge(collection.embedding_model || 'embed model n/a')}
        </div>
        <h3>${escapeHtml(collection.name)}</h3>
        <p class="meta-line">${escapeHtml(collection.id)} · ${collection.document_count ?? 0} documents</p>
        ${collection.description ? `<p class="meta-line">${escapeHtml(collection.description)}</p>` : ''}
      </button>
    `)
    .join('');

  dom.rag.collectionList.querySelectorAll('[data-rag-collection-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadRagCollection(button.dataset.ragCollectionId);
    });
  });
}

function renderRagCollectionDetail() {
  const collection = selectedRagCollection();
  if (!collection) {
    dom.rag.collectionDetail.className = 'detail-stack empty';
    dom.rag.collectionDetail.textContent = 'Select a collection to inspect document counts, embedding settings, and chunking policy.';
    return;
  }

  dom.rag.collectionDetail.className = 'detail-stack';
  dom.rag.collectionDetail.innerHTML = `
    <div class="inline-meta">${renderStatusBadge(collection.index_status || 'ready')}${renderBadge(collection.embedding_model || 'embedding model n/a')}${renderBadge(`${collection.document_count ?? 0} documents`)}</div>
    ${renderDetailGrid([
      { label: 'Collection ID', value: collection.id },
      { label: 'Name', value: collection.name },
      { label: 'Embedding model', value: collection.embedding_model || '—' },
      { label: 'Index status', value: collection.index_status || '—' },
      { label: 'Document count', value: collection.document_count ?? 0 },
      { label: 'Created', value: formatDateTime(collection.created_at) },
      { label: 'Updated', value: formatDateTime(collection.updated_at) },
    ])}
    ${collection.description ? `<section class="callout success"><p class="callout-title">Description</p><p>${escapeHtml(collection.description)}</p></section>` : ''}
    ${renderJsonDetails('Chunking policy', collection.chunking_policy_json || {}, { summaryDetail: 'Stored collection chunking policy' })}
  `;
}

function renderRagDocuments() {
  if (!selectedRagCollection()) {
    dom.rag.documentSummary.textContent = 'Collection documents will appear here.';
    dom.rag.documentList.className = 'stack-list empty';
    dom.rag.documentList.textContent = 'Collection documents will appear here.';
    return;
  }

  if (!state.rag.documents.length) {
    dom.rag.documentSummary.textContent = 'No documents uploaded for this collection yet.';
    dom.rag.documentList.className = 'stack-list empty';
    dom.rag.documentList.textContent = 'No documents uploaded for this collection yet.';
    return;
  }

  dom.rag.documentSummary.textContent = `${countLabel(state.rag.documents.length, 'document')} in the selected collection.`;
  dom.rag.documentList.className = 'stack-list';
  dom.rag.documentList.innerHTML = state.rag.documents
    .map((document) => `
      <button type="button" class="list-card${document.id === state.rag.selectedDocumentId ? ' active' : ''}" data-rag-document-id="${escapeHtml(document.id)}">
        <div class="inline-meta">
          ${renderStatusBadge(document.status || 'uploaded')}
          ${renderBadge(document.source_type || 'source n/a')}
          ${renderBadge(document.mime_type || 'mime n/a')}
        </div>
        <h3>${escapeHtml(document.filename || document.id)}</h3>
        <p class="meta-line">${escapeHtml(document.id)} · created ${escapeHtml(formatDateTime(document.created_at) || 'n/a')}</p>
        <p class="meta-line">Preview length: ${escapeHtml(String(document.preview_length ?? 0))}</p>
        ${document.preview_excerpt ? `<p class="meta-line">${escapeHtml(document.preview_excerpt)}</p>` : ''}
      </button>
    `)
    .join('');

  dom.rag.documentList.querySelectorAll('[data-rag-document-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadRagDocument(button.dataset.ragDocumentId);
    });
  });
}

function renderRagDocumentDetail() {
  const document = selectedRagDocument();
  if (!document) {
    dom.rag.documentDetail.className = 'detail-stack empty';
    dom.rag.documentDetail.textContent = 'Select a document to inspect filename, source type, and preview detail.';
    return;
  }

  dom.rag.documentDetail.className = 'detail-stack';
  dom.rag.documentDetail.innerHTML = `
    <div class="inline-meta">${renderStatusBadge(document.status || 'uploaded')}${renderBadge(document.mime_type || 'mime n/a')}${renderBadge(document.source_type || 'source n/a')}</div>
    ${renderDetailGrid([
      { label: 'Document ID', value: document.id },
      { label: 'Collection ID', value: document.collection_id },
      { label: 'Filename', value: document.filename },
      { label: 'MIME type', value: document.mime_type || '—' },
      { label: 'Status', value: document.status || '—' },
      { label: 'Source type', value: document.source_type || '—' },
      { label: 'Checksum', value: document.checksum || '—' },
      { label: 'Preview length', value: document.preview_length ?? 0 },
      { label: 'Parse method', value: document.parse_method || '—' },
      { label: 'Created', value: formatDateTime(document.created_at) },
      { label: 'Updated', value: formatDateTime(document.updated_at) },
    ])}
    ${document.preview_excerpt ? `<section class="callout success"><p class="callout-title">Preview excerpt</p><p>${escapeHtml(document.preview_excerpt)}</p></section>` : ''}
    ${document.text_preview ? `<section class="callout"><p class="callout-title">Text preview</p><p>${escapeHtml(document.text_preview)}</p></section>` : ''}
    <div class="button-row"><button type="button" class="secondary-button" data-rag-delete-document-id="${escapeHtml(document.id)}">Delete document</button></div>
    ${renderJsonDetails('Document metadata', document.metadata_json || {}, { summaryDetail: 'Parse, storage, and chunk preview metadata' })}
  `;

  dom.rag.documentDetail.querySelectorAll('[data-rag-delete-document-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      const confirmed = window.confirm(`Delete document ${document.filename || document.id}?`);
      if (!confirmed) {
        return;
      }
      try {
        await deleteRagDocument(button.dataset.ragDeleteDocumentId);
      } catch (error) {
        setRagDocumentHint(error.message);
      }
    });
  });
}

function renderRagPreviewResult() {
  const preview = state.rag.retrievalPreview;
  if (!preview) {
    dom.rag.previewResult.className = 'detail-stack empty';
    dom.rag.previewResult.textContent = 'Retrieval preview results will appear here. This preview does not call an LLM.';
    return;
  }

  dom.rag.previewResult.className = 'detail-stack';
  dom.rag.previewResult.innerHTML = `
    <section class="callout success">
      <p class="callout-title">Non-LLM retrieval preview</p>
      <p>This retrieval preview only shows collection retrieval results. It does not call an LLM.</p>
    </section>
    ${renderDetailGrid([
      { label: 'Collection', value: preview.collection_name || preview.collection_id || '—' },
      { label: 'Collection ID', value: preview.collection_id || '—' },
      { label: 'Query', value: preview.query || '—' },
      { label: 'Top k', value: preview.top_k ?? '—' },
      { label: 'Result count', value: safeArray(preview.results).length },
    ])}
    ${safeArray(preview.results).length ? renderJsonDetails('Retrieval results', preview.results, { open: true, summaryDetail: `${preview.results.length} matching document${preview.results.length === 1 ? '' : 's'}` }) : '<section class="callout warning"><p class="callout-title">No retrieval matches</p><p>No documents in the selected collection matched the preview query.</p></section>'}
  `;
}

function clearRagSelections() {
  state.rag.selectedCollectionId = null;
  state.rag.selectedCollection = null;
  state.rag.documents = [];
  state.rag.selectedDocumentId = null;
  state.rag.selectedDocument = null;
  state.rag.retrievalPreview = null;
  renderRagCollections();
  renderRagCollectionDetail();
  renderRagDocuments();
  renderRagDocumentDetail();
  renderRagPreviewResult();
}

async function refreshRagCollections({ preferredCollectionId = null, preferredDocumentId = null } = {}) {
  state.rag.collections = await fetchJson('/rag-collections');
  state.rag.selectedCollectionId = preferredCollectionId && state.rag.collections.some((collection) => collection.id === preferredCollectionId)
    ? preferredCollectionId
    : state.rag.collections.some((collection) => collection.id === state.rag.selectedCollectionId)
      ? state.rag.selectedCollectionId
      : state.rag.collections[0]?.id || null;

  renderRagCollections();

  if (!state.rag.selectedCollectionId) {
    clearRagSelections();
    return;
  }

  await loadRagCollection(state.rag.selectedCollectionId, { preferredDocumentId });
}

async function loadRagCollection(collectionId, { preferredDocumentId = null } = {}) {
  if (!collectionId) {
    clearRagSelections();
    return;
  }

  const requestToken = ++state.rag.requestTokens.collection;
  const [collection, documents] = await Promise.all([
    fetchJson(`/rag-collections/${encodeURIComponent(collectionId)}`),
    fetchJson(`/rag-collections/${encodeURIComponent(collectionId)}/documents`),
  ]);
  if (requestToken !== state.rag.requestTokens.collection) {
    return;
  }

  state.rag.selectedCollectionId = collectionId;
  state.rag.selectedCollection = collection;
  state.rag.documents = Array.isArray(documents) ? documents : [];
  state.rag.retrievalPreview = null;
  state.rag.selectedDocumentId = preferredDocumentId && state.rag.documents.some((item) => item.id === preferredDocumentId)
    ? preferredDocumentId
    : state.rag.documents.some((item) => item.id === state.rag.selectedDocumentId)
      ? state.rag.selectedDocumentId
      : state.rag.documents[0]?.id || null;

  renderRagCollections();
  renderRagCollectionDetail();
  renderRagDocuments();
  renderRagPreviewResult();

  if (!state.rag.selectedDocumentId) {
    state.rag.selectedDocument = null;
    renderRagDocumentDetail();
    return;
  }

  await loadRagDocument(state.rag.selectedDocumentId);
}

async function loadRagDocument(documentId) {
  if (!documentId) {
    state.rag.selectedDocumentId = null;
    state.rag.selectedDocument = null;
    renderRagDocuments();
    renderRagDocumentDetail();
    return;
  }

  const requestToken = ++state.rag.requestTokens.document;
  const document = await fetchJson(`/rag-documents/${encodeURIComponent(documentId)}`);
  if (requestToken !== state.rag.requestTokens.document) {
    return;
  }

  state.rag.selectedDocumentId = document.id;
  state.rag.selectedDocument = document;
  renderRagDocuments();
  renderRagDocumentDetail();
}

async function deleteRagDocument(documentId) {
  const collection = selectedRagCollection();
  const response = await fetchJson(`/rag-documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
  });
  state.rag.retrievalPreview = null;
  await loadRagCollection(response.collection_id || collection?.id || state.rag.selectedCollectionId, { preferredDocumentId: null });
  state.rag.selectedDocumentId = null;
  state.rag.selectedDocument = null;
  renderRagDocumentDetail();
  renderRagPreviewResult();
  setRagDocumentHint(`Deleted document ${response.document_id}.`);
  setRagPreviewHint('Retrieval preview was cleared after document deletion. Run it again to inspect the updated collection context. This does not call an LLM.');
}

async function ensureRagInitialized({ force = false } = {}) {
  if (state.rag.hasLoadedInitialData && !force) {
    return;
  }

  await refreshRagCollections();
  renderRagPreviewResult();
  state.rag.hasLoadedInitialData = true;
}

dom.modeButtons.forEach((button) => {
  button.addEventListener('click', async () => {
    try {
      await setMode(button.dataset.mode);
      if (button.dataset.mode === MODES.FT) {
        setFtDatasetHint('Fine-tuning datasets ready. Create or inspect a dataset version here.');
        setFtVersionHint('Review row validity, apply status transitions, and prepare the selected version for training.');
        setFtTrainingHint('Run ./scripts/ft_smoke_preflight.sh on the macOS host before enqueueing. Smoke jobs validate adapter artifacts only; they do not load an LM Studio serving model.');
        return;
      }
      if (button.dataset.mode === MODES.MODELS) {
        setModelsHint('Models ready. Select a registered model and run inference here.');
        return;
      }
      if (button.dataset.mode === MODES.RAG) {
        setRagCollectionHint('RAG collections ready. Create or inspect retrieval collections here.');
        setRagDocumentHint('Upload, review, or delete collection-managed documents here.');
        setRagPreviewHint('Run retrieval preview to inspect grounding context before inference. This does not call an LLM.');
      }
    } catch (error) {
      if (button.dataset.mode === MODES.FT) {
        setFtDatasetHint(error.message);
      } else if (button.dataset.mode === MODES.MODELS) {
        setModelsHint(error.message);
      } else if (button.dataset.mode === MODES.RAG) {
        setRagCollectionHint(error.message);
      }
    }
  });
});

window.addEventListener('beforeunload', () => {
  stopWorkflowPolling();
  stopPlcRunPolling();
  stopFtTrainingPolling();
});

dom.ft.datasetsRefresh.addEventListener('click', async () => {
  try {
    await ensureFtInitialized();
    await Promise.all([refreshFtDatasets(), refreshFtTrainingJobs()]);
    setFtDatasetHint('Fine-tuning datasets refreshed.');
  } catch (error) {
    setFtDatasetHint(error.message);
  }
});

dom.ft.createDatasetButton.addEventListener('click', async () => {
  const name = dom.ft.datasetName.value.trim();
  if (!name) {
    setFtDatasetHint('Enter a dataset name before creating a fine-tuning dataset.');
    return;
  }

  dom.ft.createDatasetButton.disabled = true;
  setFtDatasetHint('Creating fine-tuning dataset...');
  try {
    const created = await fetchJson('/ft-datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        task_type: dom.ft.datasetTaskType.value,
        schema_type: dom.ft.datasetSchemaType.value.trim() || 'json',
        description: dom.ft.datasetDescription.value.trim() || null,
      }),
    });
    await refreshFtDatasets({ preferredDatasetId: created.id });
    dom.ft.datasetName.value = '';
    dom.ft.datasetDescription.value = '';
    setFtDatasetHint(`Created dataset ${created.name}.`);
  } catch (error) {
    setFtDatasetHint(error.message);
  } finally {
    dom.ft.createDatasetButton.disabled = false;
  }
});

dom.ft.createVersionButton.addEventListener('click', async () => {
  const dataset = selectedFtDataset();
  if (!dataset) {
    setFtVersionHint('Select a dataset before creating a version.');
    return;
  }

  const versionLabel = dom.ft.versionLabel.value.trim();
  if (!versionLabel) {
    setFtVersionHint('Enter a version label before creating a dataset version.');
    return;
  }

  dom.ft.createVersionButton.disabled = true;
  setFtVersionHint(`Creating version ${versionLabel}...`);
  try {
    const created = await fetchJson(`/ft-datasets/${encodeURIComponent(dataset.id)}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        version_label: versionLabel,
        train_split_ratio: parseNumberInput(dom.ft.trainRatio.value, { fallback: 0.8, minimum: 0, fieldLabel: 'Train split' }),
        val_split_ratio: parseNumberInput(dom.ft.valRatio.value, { fallback: 0.1, minimum: 0, fieldLabel: 'Validation split' }),
        test_split_ratio: parseNumberInput(dom.ft.testRatio.value, { fallback: 0.1, minimum: 0, fieldLabel: 'Test split' }),
      }),
    });
    await refreshFtDatasets({ preferredDatasetId: dataset.id, preferredVersionId: created.id });
    dom.ft.versionLabel.value = '';
    setFtVersionHint(`Created version ${created.version_label}.`);
  } catch (error) {
    setFtVersionHint(error.message);
  } finally {
    dom.ft.createVersionButton.disabled = false;
  }
});

dom.ft.versionRefresh.addEventListener('click', async () => {
  if (!state.ft.selectedVersionId) {
    setFtVersionHint('Select a version before refreshing version detail.');
    return;
  }
  try {
    await loadFtVersion(state.ft.selectedVersionId, { preserveRow: true });
    setFtVersionHint(`Version ${state.ft.selectedVersionId} refreshed.`);
  } catch (error) {
    setFtVersionHint(error.message);
  }
});

dom.ft.applyVersionStatusButton.addEventListener('click', async () => {
  const version = selectedFtVersion();
  if (!version) {
    setFtVersionHint('Select a version before applying a status transition.');
    return;
  }

  dom.ft.applyVersionStatusButton.disabled = true;
  setFtVersionHint(`Applying ${dom.ft.versionStatusSelect.value} to ${version.version_label || version.id}...`);
  try {
    const updated = await fetchJson(`/ft-dataset-versions/${encodeURIComponent(version.id)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: dom.ft.versionStatusSelect.value }),
    });
    await refreshFtDatasets({ preferredDatasetId: updated.dataset_id, preferredVersionId: updated.id });
    setFtVersionHint(`Version ${updated.version_label || updated.id} is now ${updated.status}.`);
  } catch (error) {
    setFtVersionHint(error.message);
  } finally {
    dom.ft.applyVersionStatusButton.disabled = false;
  }
});

dom.ft.addRowButton.addEventListener('click', async () => {
  const version = selectedFtVersion();
  if (!version) {
    setFtVersionHint('Select a version before adding rows.');
    return;
  }

  dom.ft.addRowButton.disabled = true;
  setFtVersionHint(`Adding a row to ${version.version_label || version.id}...`);
  try {
    await fetchJson(`/ft-dataset-versions/${encodeURIComponent(version.id)}/rows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rows: [
          {
            split: dom.ft.rowSplit.value,
            input_json: parseOptionalJsonValue(dom.ft.rowInputJson.value, { allowStringFallback: true, fieldLabel: 'Input payload' }),
            target_json: parseOptionalJsonValue(dom.ft.rowTargetJson.value, { allowStringFallback: true, fieldLabel: 'Target payload' }),
            metadata_json: parseOptionalJsonValue(dom.ft.rowMetadataJson.value, {
              allowStringFallback: false,
              fallbackValue: {},
              requireObject: true,
              fieldLabel: 'Metadata payload',
            }),
          },
        ],
      }),
    });
    await loadFtVersion(version.id);
    dom.ft.rowInputJson.value = '';
    dom.ft.rowTargetJson.value = '';
    dom.ft.rowMetadataJson.value = '{}';
    setFtVersionHint(`Added a row to ${version.version_label || version.id}.`);
  } catch (error) {
    setFtVersionHint(error.message);
  } finally {
    dom.ft.addRowButton.disabled = false;
  }
});

dom.ft.trainingRefresh.addEventListener('click', async () => {
  try {
    await ensureFtInitialized();
    await refreshFtTrainingJobs({ preferredTrainingJobId: state.ft.selectedTrainingJobId });
    setFtTrainingHint('Fine-tuning training jobs refreshed.');
  } catch (error) {
    setFtTrainingHint(error.message);
  }
});

dom.ft.fillSmokePresetButton.addEventListener('click', () => {
  fillSmokeHyperparameterPreset();
});

dom.ft.prepareSmokeDatasetButton.addEventListener('click', async () => {
  dom.ft.prepareSmokeDatasetButton.disabled = true;
  const suffix = smokeNameSuffix();
  setFtDatasetHint(`Preparing smoke dataset ${suffix}...`);
  try {
    await ensureFtInitialized();
    const dataset = await fetchJson('/ft-datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `Local FT smoke test dataset ${suffix}`,
        task_type: 'instruction_sft',
        schema_type: 'json',
        description: 'Small local smoke-test dataset prepared from the reviewer UI for validating the SFT + LoRA artifact pipeline.',
      }),
    });
    const version = await fetchJson(`/ft-datasets/${encodeURIComponent(dataset.id)}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        version_label: `smoke-v1-${suffix}`,
        train_split_ratio: 0.75,
        val_split_ratio: 0.25,
        test_split_ratio: 0,
      }),
    });
    await fetchJson(`/ft-dataset-versions/${encodeURIComponent(version.id)}/rows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: buildSmokeDatasetRows() }),
    });
    await fetchJson(`/ft-dataset-versions/${encodeURIComponent(version.id)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'validated' }),
    });
    const locked = await fetchJson(`/ft-dataset-versions/${encodeURIComponent(version.id)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'locked' }),
    });
    await refreshFtDatasets({ preferredDatasetId: dataset.id, preferredVersionId: locked.id });
    applySmokeTrainingDefaults();
    setFtDatasetHint(`Prepared smoke dataset ${dataset.name}.`);
    setFtVersionHint(`${locked.version_label || locked.id} is locked and ready for a smoke training job.`);
    setFtTrainingHint('Smoke dataset is ready. Run ./scripts/ft_smoke_preflight.sh on the macOS host before enqueueing. Expect adapter artifacts only, not LM Studio publishing.');
  } catch (error) {
    setFtDatasetHint(error.message);
    setFtVersionHint(error.message);
    setFtTrainingHint(error.message);
  } finally {
    dom.ft.prepareSmokeDatasetButton.disabled = false;
  }
});

dom.ft.enqueueSmokeTrainingButton?.addEventListener('click', async () => {
  const version = selectedFtVersion();
  if (!version) {
    setFtTrainingHint('Select a locked version before enqueueing smoke training.');
    return;
  }
  if (version.status !== 'locked') {
    setFtTrainingHint('Smoke training requires the selected version to be locked first. Prepare the smoke dataset or lock the version before enqueueing.');
    return;
  }

  dom.ft.enqueueSmokeTrainingButton.disabled = true;
  dom.ft.enqueueTrainingButton.disabled = true;
  setFtTrainingHint(`Enqueueing smoke training for ${version.version_label || version.id}...`);
  try {
    applySmokeTrainingDefaults();
    await enqueueFtTrainingJob({
      version,
      baseModelName: SMOKE_BASE_MODEL_NAME,
      trainingMethod: 'sft_qlora',
      hyperparamsJson: SMOKE_HYPERPARAMETER_PRESET,
      queuedHint: `Smoke training job queued for ${version.version_label || version.id}. The active job is now selected and polling. Smoke training validates adapter artifact creation, not LM Studio serving readiness.`,
    });
  } catch (error) {
    setFtTrainingHint(error.message);
  } finally {
    dom.ft.enqueueTrainingButton.disabled = false;
    renderFtSmokeActions();
  }
});

dom.ft.enqueueTrainingButton.addEventListener('click', async () => {
  const version = selectedFtVersion();
  if (!version) {
    setFtTrainingHint('Select a version before enqueueing a training job.');
    return;
  }
  const baseModelName = dom.ft.baseModelName.value.trim();
  if (!baseModelName) {
    setFtTrainingHint('Enter a base model name before enqueueing training.');
    return;
  }

  const trainingMethod = dom.ft.trainingMethod.value.trim() || 'stub_adapter';
  if (trainingMethod === 'sft_qlora' && version.status !== 'locked') {
    setFtTrainingHint('Real sft_qlora training requires the selected dataset version to be locked first.');
    return;
  }

  dom.ft.enqueueTrainingButton.disabled = true;
  setFtTrainingHint(`Enqueueing training for ${version.version_label || version.id}...`);
  try {
    await enqueueFtTrainingJob({
      version,
      baseModelName,
      trainingMethod,
      hyperparamsJson: parseOptionalJsonValue(dom.ft.trainingHyperparamsJson.value, {
        allowStringFallback: false,
        fallbackValue: {},
        requireObject: true,
        fieldLabel: 'Training hyperparameters',
      }),
      queuedHint: `Training job queued for ${version.version_label || version.id}. The active job is now selected and polling.`,
    });
  } catch (error) {
    setFtTrainingHint(error.message);
  } finally {
    dom.ft.enqueueTrainingButton.disabled = false;
    renderFtSmokeActions();
  }
});

dom.models.refresh.addEventListener('click', async () => {
  try {
    await ensureModelsInitialized();
    await Promise.all([
      refreshModelsRegistry({
        preferredReviewModelId: state.models.selectedReviewModelId,
        preferredInferenceModelId: state.models.selectedInferenceModelId,
      }),
      refreshModelsRagCollections(),
    ]);
    setModelsHint('Model registry refreshed.');
  } catch (error) {
    setModelsHint(error.message);
  }
});

dom.models.modelSelect.addEventListener('change', async (event) => {
  try {
    setModelsInferenceModel(event.target.value);
    setModelsHint(`Inference model changed to ${event.target.selectedOptions[0]?.textContent || event.target.value}.`);
  } catch (error) {
    setModelsHint(error.message);
  }
});

dom.models.ragCollectionSelect.addEventListener('change', (event) => {
  state.models.selectedRagCollectionId = event.target.value;
  renderInferenceSelectionSummary();
  const selectedLabel = event.target.selectedOptions[0]?.textContent || 'No RAG collection';
  setModelsHint(`Inference RAG collection set to ${selectedLabel}.`);
});

dom.models.runButton.addEventListener('click', async () => {
  const prompt = dom.models.prompt.value.trim();
  if (!prompt) {
    setModelsHint('Enter a prompt before running inference.');
    return;
  }
  if (!state.models.selectedInferenceModelId) {
    setModelsHint('Select an inference model before running inference. Only runtime-ready/selectable models can run inference.');
    return;
  }

  dom.models.runButton.disabled = true;
  setModelsHint('Running inference...');
  try {
    const result = await fetchJson('/inference/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model_id: state.models.selectedInferenceModelId,
        rag_collection_id: state.models.selectedRagCollectionId || null,
        temperature: parseNumberInput(dom.models.temperature.value, { fallback: 0, minimum: 0, fieldLabel: 'Temperature' }),
        max_tokens: parseNumberInput(dom.models.maxTokens.value, { fallback: null, minimum: 1, fieldLabel: 'Max tokens', integer: true }),
        top_k: parseNumberInput(dom.models.topK.value, { fallback: 3, minimum: 1, fieldLabel: 'RAG top k', integer: true }),
      }),
    });
    state.models.inferenceResult = result;
    renderInferenceResult();
    setModelsHint(`Inference completed with ${result.model?.display_name || result.meta?.model || 'the inference model'}.`);
  } catch (error) {
    setModelsHint(error.message);
  } finally {
    dom.models.runButton.disabled = false;
  }
});

dom.rag.collectionsRefresh.addEventListener('click', async () => {
  try {
    await ensureRagInitialized();
    await refreshRagCollections({ preferredCollectionId: state.rag.selectedCollectionId, preferredDocumentId: state.rag.selectedDocumentId });
    await refreshWorkflowRagCollections();
    setRagCollectionHint('RAG collections refreshed.');
  } catch (error) {
    setRagCollectionHint(error.message);
  }
});

dom.rag.createCollectionButton.addEventListener('click', async () => {
  const name = dom.rag.collectionName.value.trim();
  if (!name) {
    setRagCollectionHint('Enter a collection name before creating a RAG collection.');
    return;
  }

  dom.rag.createCollectionButton.disabled = true;
  setRagCollectionHint('Creating RAG collection...');
  try {
    const created = await fetchJson('/rag-collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        description: dom.rag.collectionDescription.value.trim() || null,
        embedding_model: dom.rag.embeddingModel.value.trim() || null,
        chunking_policy_json: parseOptionalJsonValue(dom.rag.chunkingPolicyJson.value, {
          allowStringFallback: false,
          fallbackValue: {},
          requireObject: true,
          fieldLabel: 'Chunking policy',
        }),
      }),
    });
    await refreshRagCollections({ preferredCollectionId: created.id });
    await refreshWorkflowRagCollections();
    dom.rag.collectionName.value = '';
    dom.rag.collectionDescription.value = '';
    setRagCollectionHint(`Created RAG collection ${created.name}.`);
  } catch (error) {
    setRagCollectionHint(error.message);
  } finally {
    dom.rag.createCollectionButton.disabled = false;
  }
});

dom.rag.documentsRefresh.addEventListener('click', async () => {
  if (!state.rag.selectedCollectionId) {
    setRagDocumentHint('Select a collection before refreshing document detail.');
    return;
  }
  try {
    await loadRagCollection(state.rag.selectedCollectionId, { preferredDocumentId: state.rag.selectedDocumentId });
    setRagDocumentHint(`Documents refreshed for ${selectedRagCollection()?.name || state.rag.selectedCollectionId}.`);
  } catch (error) {
    setRagDocumentHint(error.message);
  }
});

dom.rag.uploadDocumentButton.addEventListener('click', async () => {
  const collection = selectedRagCollection();
  if (!collection) {
    setRagDocumentHint('Select a collection before uploading documents.');
    return;
  }
  const file = dom.rag.documentFile.files[0];
  if (!file) {
    setRagDocumentHint('Choose a TXT, Markdown, or PDF file before uploading.');
    return;
  }

  dom.rag.uploadDocumentButton.disabled = true;
  setRagDocumentHint(`Uploading ${file.name}...`);
  try {
    const formData = new FormData();
    formData.append('file', file);
    const uploaded = await fetchJson(buildUrl(`/rag-collections/${encodeURIComponent(collection.id)}/documents`, { source_type: dom.rag.documentSourceType.value || 'upload' }), {
      method: 'POST',
      body: formData,
    });
    await loadRagCollection(collection.id, { preferredDocumentId: uploaded.id });
    dom.rag.documentFile.value = '';
    setRagDocumentHint(`Uploaded ${uploaded.filename} into ${collection.name}.`);
  } catch (error) {
    setRagDocumentHint(error.message);
  } finally {
    dom.rag.uploadDocumentButton.disabled = false;
  }
});

dom.rag.previewButton.addEventListener('click', async () => {
  const collection = selectedRagCollection();
  if (!collection) {
    setRagPreviewHint('Select a collection before running retrieval preview.');
    return;
  }
  const query = dom.rag.previewQuery.value.trim();
  if (!query) {
    setRagPreviewHint('Enter a preview query before running retrieval preview.');
    return;
  }

  dom.rag.previewButton.disabled = true;
  setRagPreviewHint('Running retrieval preview...');
  try {
    state.rag.retrievalPreview = await fetchJson('/rag-retrieval/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collection_id: collection.id,
        query,
        top_k: parseNumberInput(dom.rag.previewTopK.value, { fallback: 3, minimum: 1, fieldLabel: 'Preview top k', integer: true }),
      }),
    });
    renderRagPreviewResult();
    setRagPreviewHint(`Retrieval preview completed for ${collection.name}. This did not call an LLM.`);
  } catch (error) {
    setRagPreviewHint(error.message);
  } finally {
    dom.rag.previewButton.disabled = false;
  }
});

async function boot() {
  renderMode();
  renderFtSmokeActions();
  try {
    setFtDatasetHint('Manage datasets, version rows, and lock a version before enqueueing training.');
    setFtVersionHint('Select a dataset version to inspect rows and apply status transitions.');
    setFtTrainingHint('Run ./scripts/ft_smoke_preflight.sh on the macOS host before enqueueing. Smoke jobs validate adapter artifacts, not LM Studio serving readiness.');
    setModelsHint('Inspect registered models and run inference here.');
    setRagCollectionHint('Create or inspect retrieval collections here.');
    setRagDocumentHint('Select a RAG collection to inspect, upload, or delete documents.');
    setRagPreviewHint('Select a RAG collection and run retrieval preview here. This does not call an LLM.');
    renderInferenceResult();
    renderRagPreviewResult();
  } catch (error) {
    setFtDatasetHint(error.message);
  }
}

boot();

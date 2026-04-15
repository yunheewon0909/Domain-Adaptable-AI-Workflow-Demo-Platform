const MODES = {
  WORKFLOW: 'workflow',
  PLC: 'plc',
};

const TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed']);
const ACTIVE_JOB_STATUSES = new Set(['queued', 'running']);

const state = {
  mode: MODES.WORKFLOW,
  workflow: {
    datasets: [],
    workflows: [],
    selectedDatasetKey: null,
    selectedWorkflowKey: null,
    pollHandle: null,
  },
  plc: {
    hasLoadedInitialData: false,
    dashboardScope: 'selected',
    summary: null,
    targets: [],
    selectedTargetKey: 'stub-local',
    suites: [],
    selectedSuiteId: null,
    selectedSuite: null,
    testcases: [],
    suiteSuggestions: [],
    selectedTestcaseId: null,
    normalization: null,
    suggestions: [],
    selectedSuggestionId: null,
    selectedSuggestion: null,
    runs: [],
    selectedRunId: null,
    selectedRun: null,
    runItems: [],
    selectedRunItemId: null,
    filters: {
      testcaseQuery: '',
      testcaseInstruction: '',
      testcaseInputType: '',
      testcaseOutcome: '',
      testcaseSuggestionStatus: '',
      runQuery: '',
      runTargetKey: '',
      runStatus: '',
      runProblemsOnly: false,
      itemQuery: '',
      itemStatus: '',
      itemProblemsOnly: false,
    },
    pollHandle: null,
    pollRunId: null,
    requestTokens: {
      targets: 0,
      suite: 0,
      normalization: 0,
      suiteSuggestions: 0,
      suggestions: 0,
      suggestionDetail: 0,
      run: 0,
    },
  },
};

const dom = {
  modeButtons: Array.from(document.querySelectorAll('[data-mode]')),
  workflowMode: document.querySelector('#workflow-mode'),
  plcMode: document.querySelector('#plc-mode'),
  workflow: {
    datasetSelect: document.querySelector('#dataset-select'),
    workflowList: document.querySelector('#workflow-list'),
    promptInput: document.querySelector('#prompt-input'),
    runButton: document.querySelector('#run-button'),
    runHint: document.querySelector('#run-hint'),
    jobStatus: document.querySelector('#job-status'),
    resultPanel: document.querySelector('#result-panel'),
    evidencePanel: document.querySelector('#evidence-panel'),
  },
  plc: {
    summaryRefresh: document.querySelector('#plc-summary-refresh'),
    summaryScopeSelect: document.querySelector('#plc-dashboard-scope'),
    summaryScopeLine: document.querySelector('#plc-summary-scope'),
    summaryCards: document.querySelector('#plc-summary-cards'),
    recentRuns: document.querySelector('#plc-recent-runs'),
    failureHotspots: document.querySelector('#plc-failure-hotspots'),
    targetStatuses: document.querySelector('#plc-target-statuses'),
    instructionFailureStats: document.querySelector('#plc-instruction-failure-stats'),
    importTitle: document.querySelector('#plc-suite-title'),
    importFile: document.querySelector('#plc-suite-file'),
    importButton: document.querySelector('#plc-import-button'),
    importHint: document.querySelector('#plc-import-hint'),
    suitesRefresh: document.querySelector('#plc-suites-refresh'),
    suiteList: document.querySelector('#plc-suite-list'),
    suiteDetail: document.querySelector('#plc-suite-detail'),
    testcaseList: document.querySelector('#plc-testcase-list'),
    testcaseFilterInput: document.querySelector('#plc-testcase-filter'),
    testcaseInstructionFilter: document.querySelector('#plc-testcase-instruction-filter'),
    testcaseInputTypeFilter: document.querySelector('#plc-testcase-input-type-filter'),
    testcaseOutcomeFilter: document.querySelector('#plc-testcase-outcome-filter'),
    testcaseSuggestionFilter: document.querySelector('#plc-testcase-suggestion-filter'),
    testcaseFilterSummary: document.querySelector('#plc-testcase-filter-summary'),
    testcaseDetail: document.querySelector('#plc-testcase-detail'),
    normalizationRefresh: document.querySelector('#plc-normalization-refresh'),
    normalizationPanel: document.querySelector('#plc-normalization-panel'),
    normalizationPersistButton: document.querySelector('#plc-normalization-persist'),
    suggestionsRefresh: document.querySelector('#plc-suggestions-refresh'),
    suggestionList: document.querySelector('#plc-suggestion-list'),
    suggestionDetail: document.querySelector('#plc-suggestion-detail'),
    targetSelect: document.querySelector('#plc-target-select'),
    targetSummary: document.querySelector('#plc-target-summary'),
    runSelectedOnly: document.querySelector('#plc-run-selected-only'),
    runButton: document.querySelector('#plc-run-button'),
    runHint: document.querySelector('#plc-run-hint'),
    runsRefresh: document.querySelector('#plc-runs-refresh'),
    runFilterInput: document.querySelector('#plc-run-filter'),
    runTargetFilter: document.querySelector('#plc-run-target-filter'),
    runStatusFilter: document.querySelector('#plc-run-status-filter'),
    runProblemsOnly: document.querySelector('#plc-run-problems-only'),
    runFilterSummary: document.querySelector('#plc-run-filter-summary'),
    runList: document.querySelector('#plc-run-list'),
    runDetailRefresh: document.querySelector('#plc-run-detail-refresh'),
    runLifecycle: document.querySelector('#plc-run-lifecycle'),
    runSummary: document.querySelector('#plc-run-summary'),
    runItemFilterInput: document.querySelector('#plc-run-item-filter'),
    runItemStatusFilter: document.querySelector('#plc-run-item-status-filter'),
    runItemProblemsOnly: document.querySelector('#plc-run-item-problems-only'),
    runItemFilterSummary: document.querySelector('#plc-run-item-filter-summary'),
    runItemList: document.querySelector('#plc-run-item-list'),
    runItemDetail: document.querySelector('#plc-run-item-detail'),
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

function uniqueSortedValues(values) {
  return Array.from(new Set(safeArray(values).filter(Boolean).map((value) => String(value).trim()).filter(Boolean))).sort((left, right) =>
    left.localeCompare(right),
  );
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

function currentPlcDashboardSuiteId() {
  return state.plc.dashboardScope === 'selected' ? state.plc.selectedSuiteId : null;
}

function dashboardScopeSummary() {
  if (state.plc.dashboardScope === 'all') {
    return {
      label: 'All imported suites',
      detail: 'Refresh returns queue and failure data across every PLC suite in the demo.',
    };
  }

  const suite = selectedPlcSuite();
  if (!suite) {
    return {
      label: 'Selected suite only',
      detail: 'No suite is selected yet, so the dashboard is temporarily showing all suites until you choose one.',
    };
  }

  return {
    label: `${suite.title} (${suite.id})`,
    detail: 'Refresh follows the currently selected suite so dashboard cards and hotspot lists stay aligned with the reviewer context.',
  };
}

function latestSuggestionForTestcase(testcaseId) {
  return state.plc.suiteSuggestions.find((suggestion) => suggestion.testcase_id === testcaseId) || null;
}

function suggestionContextForTestcase(testcaseId) {
  const suggestions = state.plc.suiteSuggestions.filter((suggestion) => suggestion.testcase_id === testcaseId);
  const latest = suggestions[0] || null;
  return {
    count: suggestions.length,
    latest,
    latestStatus: latest?.status || null,
    reviewRequired: Boolean(latest?.suggestion_payload_json?.review_required),
  };
}

function hasSavedSuggestionStatus(testcaseId, status) {
  const context = suggestionContextForTestcase(testcaseId);
  if (status === 'none') {
    return context.count === 0;
  }
  if (status === 'review-required') {
    return context.reviewRequired;
  }
  return context.latestStatus === status;
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

function targetForKey(targetKey) {
  return state.plc.targets.find((target) => target.key === targetKey) || null;
}

function selectedPlcTarget() {
  return state.plc.targets.find((target) => target.key === state.plc.selectedTargetKey) || null;
}

function selectedPlcSuggestion() {
  return state.plc.selectedSuggestion;
}

function hasRunProblems(run) {
  const summary = run.summary || {};
  return run.status === 'failed' || Number(summary.failed_count || 0) > 0 || Number(summary.error_count || 0) > 0;
}

function hasRunItemProblems(item) {
  return item.status === 'failed' || item.status === 'error';
}

function filteredPlcTestcases() {
  return state.plc.testcases.filter((testcase) => {
    if (state.plc.filters.testcaseInstruction && testcase.instruction_name !== state.plc.filters.testcaseInstruction) {
      return false;
    }
    if (state.plc.filters.testcaseInputType && testcase.input_type !== state.plc.filters.testcaseInputType) {
      return false;
    }
    if (state.plc.filters.testcaseOutcome && testcase.expected_outcome !== state.plc.filters.testcaseOutcome) {
      return false;
    }
    if (state.plc.filters.testcaseSuggestionStatus && !hasSavedSuggestionStatus(testcase.id, state.plc.filters.testcaseSuggestionStatus)) {
      return false;
    }
    return matchesTextFilter(
      [
        testcase.id,
        testcase.case_key,
        testcase.instruction_name,
        testcase.execution_profile_key,
        testcase.description,
        testcase.input_type,
        testcase.output_type,
        ...(Array.isArray(testcase.tags) ? testcase.tags : []),
      ],
      state.plc.filters.testcaseQuery,
    );
  });
}

function filteredPlcRuns() {
  return state.plc.runs.filter((run) => {
    if (state.plc.filters.runTargetKey && (run.target_key || run.payload_json?.target_key) !== state.plc.filters.runTargetKey) {
      return false;
    }
    if (state.plc.filters.runStatus && run.status !== state.plc.filters.runStatus) {
      return false;
    }
    if (state.plc.filters.runProblemsOnly && !hasRunProblems(run)) {
      return false;
    }
    return matchesTextFilter(
      [run.id, run.plc_suite_id, run.payload_json?.suite_title, run.payload_json?.target_key, run.target_key, run.status],
      state.plc.filters.runQuery,
    );
  });
}

function filteredPlcRunItems() {
  return state.plc.runItems.filter((item) => {
    const requestContext = item.request_context_json || {};
    const testcaseContext = requestContext.testcase_context || {};
    const targetContext = requestContext.target_context || {};
    if (state.plc.filters.itemStatus && item.status !== state.plc.filters.itemStatus) {
      return false;
    }
    if (state.plc.filters.itemProblemsOnly && !hasRunItemProblems(item)) {
      return false;
    }
    return matchesTextFilter(
      [
        item.id,
        item.testcase_id,
        item.case_key,
        item.instruction_name,
        item.failure_reason,
        item.status,
        item.input_type,
        item.output_type,
        item.expected_outcome,
        testcaseContext.description,
        targetContext.key,
        targetContext.display_name,
        targetContext.environment_label,
        ...(safeArray(testcaseContext.tags)),
        ...(safeArray(targetContext.tags)),
      ],
      state.plc.filters.itemQuery,
    );
  });
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

function selectedWorkflow() {
  return state.workflow.workflows.find((workflow) => workflow.key === state.workflow.selectedWorkflowKey) || null;
}

function selectedPlcSuite() {
  return state.plc.selectedSuite;
}

function selectedPlcTestcase() {
  return state.plc.testcases.find((testcase) => testcase.id === state.plc.selectedTestcaseId) || null;
}

function selectedPlcRunItem() {
  return state.plc.runItems.find((item) => item.id === state.plc.selectedRunItemId) || null;
}

function setWorkflowHint(message) {
  dom.workflow.runHint.textContent = message || '';
}

function setPlcImportHint(message) {
  dom.plc.importHint.textContent = message || '';
}

function setPlcRunHint(message) {
  dom.plc.runHint.textContent = message || '';
}

function stopWorkflowPolling() {
  window.clearInterval(state.workflow.pollHandle);
  state.workflow.pollHandle = null;
}

function stopPlcRunPolling() {
  window.clearInterval(state.plc.pollHandle);
  state.plc.pollHandle = null;
  state.plc.pollRunId = null;
}

async function setMode(mode) {
  state.mode = mode;
  renderMode();
  if (mode === MODES.PLC) {
    await ensurePlcInitialized();
  }
}

function renderMode() {
  dom.workflowMode.hidden = state.mode !== MODES.WORKFLOW;
  dom.plcMode.hidden = state.mode !== MODES.PLC;
  dom.modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

function renderWorkflowDatasets() {
  dom.workflow.datasetSelect.innerHTML = '';
  state.workflow.datasets.forEach((dataset) => {
    const option = document.createElement('option');
    option.value = dataset.key;
    option.textContent = `${dataset.title}${dataset.is_active ? ' (active)' : ''}`;
    if (dataset.key === state.workflow.selectedDatasetKey) {
      option.selected = true;
    }
    dom.workflow.datasetSelect.append(option);
  });
}

function renderWorkflowList() {
  dom.workflow.workflowList.innerHTML = '';
  state.workflow.workflows.forEach((workflow) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `workflow-card${workflow.key === state.workflow.selectedWorkflowKey ? ' active' : ''}`;
    button.innerHTML = `<h3>${escapeHtml(workflow.title)}</h3><p>${escapeHtml(workflow.summary)}</p>`;
    button.addEventListener('click', () => {
      state.workflow.selectedWorkflowKey = workflow.key;
      renderWorkflowList();
      dom.workflow.promptInput.placeholder = workflow.prompt_label;
    });
    dom.workflow.workflowList.append(button);
  });
}

function renderWorkflowJob(job) {
  dom.workflow.jobStatus.textContent = JSON.stringify(job, null, 2);
  dom.workflow.jobStatus.classList.remove('empty');
}

function renderWorkflowListGroup(label, items) {
  return `<section class="result-group"><h3>${escapeHtml(label)}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></section>`;
}

function renderWorkflowEvidenceCard(item) {
  const score = Number(item.score);
  const scoreLabel = Number.isFinite(score) ? score.toFixed(6) : 'n/a';
  return `
    <article class="evidence-card">
      <h3>${escapeHtml(item.title || item.source_path || 'Evidence')}</h3>
      <p class="evidence-meta">chunk=${escapeHtml(item.chunk_id || 'n/a')} · source=${escapeHtml(item.source_path || 'n/a')} · score=${escapeHtml(scoreLabel)}</p>
      <p>${escapeHtml(item.text || '')}</p>
    </article>
  `;
}

function renderWorkflowResult(job) {
  const result = job.result_json || null;
  if (!result) {
    dom.workflow.resultPanel.className = 'result-panel empty';
    dom.workflow.resultPanel.textContent = job.status === 'failed' ? `Workflow failed: ${job.error || 'unknown error'}` : 'Waiting for result payload.';
    dom.workflow.evidencePanel.className = 'evidence-list empty';
    dom.workflow.evidencePanel.textContent = job.status === 'failed' ? 'No evidence returned because the workflow did not complete successfully.' : 'Evidence will appear after completion.';
    return;
  }

  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  const fragments = [];
  if (result.summary) {
    fragments.push(`<section class="result-group"><h3>Summary</h3><p>${escapeHtml(result.summary)}</p></section>`);
  }
  if (Array.isArray(result.key_points)) {
    fragments.push(renderWorkflowListGroup('Key points', result.key_points));
  }
  if (Array.isArray(result.recommendations)) {
    fragments.push(renderWorkflowListGroup('Recommendations', result.recommendations));
  }
  if (result.rationale) {
    fragments.push(`<section class="result-group"><h3>Rationale</h3><p>${escapeHtml(result.rationale)}</p></section>`);
  }
  if (result.title) {
    fragments.push(`<section class="result-group"><h3>Title</h3><p>${escapeHtml(result.title)}</p></section>`);
  }
  if (result.executive_summary) {
    fragments.push(`<section class="result-group"><h3>Executive summary</h3><p>${escapeHtml(result.executive_summary)}</p></section>`);
  }
  if (Array.isArray(result.findings)) {
    fragments.push(renderWorkflowListGroup('Findings', result.findings));
  }
  if (Array.isArray(result.actions)) {
    fragments.push(renderWorkflowListGroup('Actions', result.actions));
  }
  if (!fragments.length) {
    fragments.push(`<pre class="json-block">${formatJson(result)}</pre>`);
  }

  dom.workflow.resultPanel.className = 'result-panel';
  dom.workflow.resultPanel.innerHTML = fragments.join('');
  dom.workflow.evidencePanel.className = evidence.length ? 'evidence-list' : 'evidence-list empty';
  dom.workflow.evidencePanel.innerHTML = evidence.length ? evidence.map(renderWorkflowEvidenceCard).join('') : 'No evidence returned.';
}

async function refreshWorkflowDatasets() {
  state.workflow.datasets = await fetchJson('/datasets');
  const active = state.workflow.datasets.find((dataset) => dataset.is_active) || state.workflow.datasets[0] || null;
  state.workflow.selectedDatasetKey = active ? active.key : null;
  renderWorkflowDatasets();
}

async function refreshWorkflowCatalog() {
  state.workflow.workflows = await fetchJson('/workflows');
  state.workflow.selectedWorkflowKey = state.workflow.selectedWorkflowKey || state.workflow.workflows[0]?.key || null;
  renderWorkflowList();
  const workflow = selectedWorkflow();
  if (workflow) {
    dom.workflow.promptInput.placeholder = workflow.prompt_label;
  }
}

function beginWorkflowPolling(jobId) {
  stopWorkflowPolling();
  state.workflow.pollHandle = window.setInterval(async () => {
    try {
      const job = await fetchJson(`/jobs/${jobId}`);
      renderWorkflowJob(job);
      renderWorkflowResult(job);
      if (TERMINAL_JOB_STATUSES.has(job.status)) {
        stopWorkflowPolling();
        dom.workflow.runButton.disabled = false;
        setWorkflowHint(job.status === 'succeeded' ? 'Workflow completed.' : `Workflow failed: ${job.error || 'unknown error'}`);
      }
    } catch (error) {
      stopWorkflowPolling();
      dom.workflow.runButton.disabled = false;
      setWorkflowHint(error.message);
    }
  }, 1200);
}

async function activateDataset(datasetKey) {
  await fetchJson('/datasets/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_key: datasetKey }),
  });
  await refreshWorkflowDatasets();
}

function renderPlcDashboard() {
  const summary = state.plc.summary;
  const scope = dashboardScopeSummary();
  dom.plc.summaryScopeSelect.value = state.plc.dashboardScope;
  dom.plc.summaryScopeLine.textContent = `${scope.label} — ${scope.detail}`;
  if (!summary) {
    dom.plc.summaryCards.className = 'stat-grid empty';
    dom.plc.summaryCards.textContent = 'PLC dashboard metrics will appear here.';
    dom.plc.recentRuns.className = 'stack-list empty';
    dom.plc.recentRuns.textContent = 'No PLC runs yet.';
    dom.plc.failureHotspots.className = 'stack-list empty';
    dom.plc.failureHotspots.textContent = 'No failures captured yet.';
    dom.plc.targetStatuses.className = 'stack-list empty';
    dom.plc.targetStatuses.textContent = 'Target status snapshots will appear here.';
    dom.plc.instructionFailureStats.className = 'stack-list empty';
    dom.plc.instructionFailureStats.textContent = 'Instruction failure trends will appear here.';
    return;
  }

  const queueStats = summary.queue_stats || {};
  const selectedSuiteId = currentPlcDashboardSuiteId();
  const cards = [
    { label: selectedSuiteId ? 'Scoped suites' : 'Suites', value: summary.suite_count ?? 0 },
    { label: 'Runs', value: summary.run_count ?? 0 },
    { label: 'Queued', value: queueStats.queued ?? 0 },
    { label: 'Running', value: queueStats.running ?? 0 },
    { label: 'Succeeded', value: queueStats.succeeded ?? 0 },
    { label: 'Failed', value: queueStats.failed ?? 0 },
  ];
  dom.plc.summaryCards.className = 'stat-grid';
  dom.plc.summaryCards.innerHTML = cards
    .map(
      (card) => `
        <article class="stat-card">
          <p class="stat-label">${escapeHtml(card.label)}</p>
          <p class="stat-value">${escapeHtml(card.value)}</p>
        </article>
      `,
    )
    .join('');

  const recentRuns = Array.isArray(summary.recent_runs) ? summary.recent_runs : [];
  dom.plc.recentRuns.className = recentRuns.length ? 'stack-list' : 'stack-list empty';
  dom.plc.recentRuns.innerHTML = recentRuns.length
    ? recentRuns
        .map(
          (run) => `
            <article class="list-card">
              <div class="inline-meta">
                ${renderStatusBadge(run.status)}
                <span class="meta-line">run ${escapeHtml(run.id)}</span>
                ${run.target_key ? renderBadge(`target ${run.target_key}`) : ''}
              </div>
              <h3>${escapeHtml(run.suite_title || run.plc_suite_id || 'suite')}</h3>
              <p class="meta-line">suite ${escapeHtml(run.plc_suite_id || '—')} · created ${escapeHtml(formatDateTime(run.created_at))}</p>
              <div class="badge-row">
                ${renderBadge(`pass ${run.summary?.passed_count ?? 0}`)}
                ${renderBadge(`fail ${run.summary?.failed_count ?? 0}`)}
                ${renderBadge(`error ${run.summary?.error_count ?? 0}`)}
              </div>
            </article>
          `,
        )
        .join('')
    : 'No PLC runs yet.';

  const failureHotspots = Array.isArray(summary.failure_hotspots) ? summary.failure_hotspots : [];
  dom.plc.failureHotspots.className = failureHotspots.length ? 'stack-list' : 'stack-list empty';
  dom.plc.failureHotspots.innerHTML = failureHotspots.length
    ? failureHotspots
        .map(
          (item) => `
            <article class="list-card">
              <h3>${escapeHtml(item.case_key)}</h3>
              <p class="meta-line">${escapeHtml(item.count)} recorded failures · ${escapeHtml(item.instruction_name || 'unknown instruction')}</p>
              ${item.latest_failure_reason ? `<p class="detail-copy">${escapeHtml(item.latest_failure_reason)}</p>` : ''}
            </article>
          `,
        )
        .join('')
    : 'No failures captured yet.';

  const targetStatuses = safeArray(summary.target_statuses);
  dom.plc.targetStatuses.className = targetStatuses.length ? 'stack-list' : 'stack-list empty';
  dom.plc.targetStatuses.innerHTML = targetStatuses.length
    ? targetStatuses
        .map((targetStatus) => {
          const target = targetForKey(targetStatus.target_key);
          return `
            <article class="list-card">
              <div class="inline-meta">
                ${renderStatusBadge(targetStatus.status)}
                ${renderBadge(targetStatus.target_key || 'unknown target')}
              </div>
              <h3>${escapeHtml(target?.display_name || targetStatus.target_key || 'Target')}</h3>
              <p class="meta-line">suite ${escapeHtml(targetStatus.suite_id || '—')} · updated ${escapeHtml(formatDateTime(targetStatus.created_at))}</p>
              <div class="badge-row">
                ${target?.environment_label ? renderBadge(target.environment_label) : ''}
                ${target?.line ? renderBadge(`line ${target.line}`) : ''}
                ${target?.bench ? renderBadge(`bench ${target.bench}`) : ''}
              </div>
              <div class="badge-row">
                ${renderBadge(`pass ${targetStatus.summary?.passed_count ?? 0}`)}
                ${renderBadge(`fail ${targetStatus.summary?.failed_count ?? 0}`)}
                ${renderBadge(`error ${targetStatus.summary?.error_count ?? 0}`)}
              </div>
            </article>
          `;
        })
        .join('')
    : 'Target status snapshots will appear here.';

  const instructionFailureStats = safeArray(summary.instruction_failure_stats);
  dom.plc.instructionFailureStats.className = instructionFailureStats.length ? 'stack-list' : 'stack-list empty';
  dom.plc.instructionFailureStats.innerHTML = instructionFailureStats.length
    ? instructionFailureStats
        .map(
          (entry) => `
            <article class="list-card">
              <div class="inline-meta">
                ${renderBadge(`failures ${entry.count}`)}
              </div>
              <h3>${escapeHtml(entry.instruction_name || 'unknown instruction')}</h3>
              <p class="meta-line">Instruction-level failure concentration across the current dashboard scope.</p>
            </article>
          `,
        )
        .join('')
    : 'Instruction failure trends will appear here.';
}

function renderPlcTargets() {
  const targets = state.plc.targets;
  if (!targets.length) {
    dom.plc.targetSelect.innerHTML = '';
    dom.plc.targetSelect.disabled = true;
    populateSelectOptions(dom.plc.runTargetFilter, [], {
      placeholderLabel: 'All targets',
      selectedValue: state.plc.filters.runTargetKey,
    });
    dom.plc.targetSummary.className = 'callout empty';
    dom.plc.targetSummary.textContent = 'Available PLC targets will appear here.';
    return;
  }

  dom.plc.targetSelect.disabled = false;
  dom.plc.targetSelect.innerHTML = targets
    .map(
      (target) => `
        <option value="${escapeHtml(target.key)}" ${target.key === state.plc.selectedTargetKey ? 'selected' : ''} ${target.is_active ? '' : 'disabled'}>
          ${escapeHtml(target.display_name || target.key)}${target.is_active ? '' : ' (inactive)'}
        </option>
      `,
    )
    .join('');
  if (state.plc.filters.runTargetKey && !targets.some((target) => target.key === state.plc.filters.runTargetKey)) {
    state.plc.filters.runTargetKey = '';
  }
  populateSelectOptions(
    dom.plc.runTargetFilter,
    targets.map((target) => target.key),
    { placeholderLabel: 'All targets', selectedValue: state.plc.filters.runTargetKey },
  );

  const target = selectedPlcTarget();
  if (!target) {
    dom.plc.targetSummary.className = 'callout empty';
    dom.plc.targetSummary.textContent = 'Select a PLC target to review target metadata before running.';
    return;
  }

  dom.plc.targetSummary.className = `callout${target.is_active ? '' : ' warning'}`;
  dom.plc.targetSummary.innerHTML = `
    <p class="callout-title">Selected target</p>
    <div class="inline-meta">
      ${renderBadge(target.display_name || target.key)}
      ${renderBadge(`key ${target.key}`)}
      ${renderBadge(`mode ${target.executor_mode || 'unknown'}`)}
      ${renderStatusBadge(target.is_active ? 'active' : 'inactive')}
    </div>
    ${renderDetailGrid([
      { label: 'Environment', value: target.environment_label || '—' },
      { label: 'Line', value: target.line || '—' },
      { label: 'Bench', value: target.bench || '—' },
      { label: 'Target tags', value: safeArray(target.tags).join(', ') || '—' },
    ])}
    <p class="detail-copy">${escapeHtml(target.description || 'No target description available.')}</p>
    ${target.metadata_json?.attributes_json && Object.keys(target.metadata_json.attributes_json).length ? renderJsonDetails('Additional target metadata', target.metadata_json.attributes_json) : ''}
  `;
}

function renderPlcSuites() {
  if (!state.plc.suites.length) {
    dom.plc.suiteList.className = 'stack-list empty';
    dom.plc.suiteList.textContent = 'No PLC suites imported yet.';
    return;
  }

  dom.plc.suiteList.className = 'stack-list';
  dom.plc.suiteList.innerHTML = state.plc.suites
    .map(
      (suite) => `
        <button type="button" class="list-card${suite.id === state.plc.selectedSuiteId ? ' active' : ''}" data-suite-id="${escapeHtml(suite.id)}">
          <div class="inline-meta">
            ${renderBadge(`${suite.case_count} cases`)}
            ${renderBadge(suite.source_format.toUpperCase())}
          </div>
          <h3>${escapeHtml(suite.title)}</h3>
          <p class="meta-line">${escapeHtml(suite.id)} · imported ${escapeHtml(formatDateTime(suite.created_at))}</p>
          <p class="meta-line">source ${escapeHtml(suite.source_filename)}</p>
        </button>
      `,
    )
    .join('');

  dom.plc.suiteList.querySelectorAll('[data-suite-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadPlcSuite(button.dataset.suiteId);
    });
  });
}

function renderPlcSuiteDetail() {
  const suite = selectedPlcSuite();
  if (!suite) {
    dom.plc.suiteDetail.className = 'detail-stack empty';
    dom.plc.suiteDetail.textContent = 'Select a suite to inspect testcase summaries.';
    return;
  }

  const warnings = Array.isArray(suite.definition_json?.warnings) ? suite.definition_json.warnings : [];
  const expectedFailCount = state.plc.testcases.filter((testcase) => testcase.expected_outcome === 'fail').length;
  const instructionCount = uniqueSortedValues(state.plc.testcases.map((testcase) => testcase.instruction_name)).length;
  const inputTypeCount = uniqueSortedValues(state.plc.testcases.map((testcase) => testcase.input_type)).length;
  const fragments = [
    renderDetailGrid([
      { label: 'Suite ID', value: suite.id },
      { label: 'Title', value: suite.title },
      { label: 'Source file', value: suite.source_filename },
      { label: 'Format', value: suite.source_format.toUpperCase() },
      { label: 'Case count', value: suite.case_count },
      { label: 'Expected-fail cases', value: expectedFailCount },
      { label: 'Instruction count', value: instructionCount },
      { label: 'Input types', value: inputTypeCount },
      { label: 'Saved suggestions', value: state.plc.suiteSuggestions.length },
      { label: 'Updated', value: formatDateTime(suite.updated_at) },
    ]),
  ];

  if (warnings.length) {
    fragments.push(`
      <section class="callout warning">
        <p class="callout-title">Import warnings</p>
        <div class="detail-stack">
          ${warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join('')}
        </div>
      </section>
    `);
  }

  dom.plc.suiteDetail.className = 'detail-stack';
  dom.plc.suiteDetail.innerHTML = fragments.join('');
}

function renderPlcTestcaseFilters() {
  const instructions = uniqueSortedValues(state.plc.testcases.map((testcase) => testcase.instruction_name));
  const inputTypes = uniqueSortedValues(state.plc.testcases.map((testcase) => testcase.input_type));
  if (state.plc.filters.testcaseInstruction && !instructions.includes(state.plc.filters.testcaseInstruction)) {
    state.plc.filters.testcaseInstruction = '';
  }
  if (state.plc.filters.testcaseInputType && !inputTypes.includes(state.plc.filters.testcaseInputType)) {
    state.plc.filters.testcaseInputType = '';
  }
  populateSelectOptions(dom.plc.testcaseInstructionFilter, instructions, {
    placeholderLabel: 'All instructions',
    selectedValue: state.plc.filters.testcaseInstruction,
  });
  populateSelectOptions(dom.plc.testcaseInputTypeFilter, inputTypes, {
    placeholderLabel: 'All input types',
    selectedValue: state.plc.filters.testcaseInputType,
  });
  dom.plc.testcaseSuggestionFilter.value = state.plc.filters.testcaseSuggestionStatus;
}

function renderPlcTestcaseList() {
  const visibleTestcases = filteredPlcTestcases();
  if (!state.plc.testcases.length) {
    dom.plc.testcaseFilterSummary.textContent = 'Suite testcases will appear here.';
    dom.plc.testcaseList.className = 'stack-list empty';
    dom.plc.testcaseList.textContent = 'Suite testcases will appear here.';
    return;
  }

  const expectedFailCount = state.plc.testcases.filter((testcase) => testcase.expected_outcome === 'fail').length;
  const savedSuggestionCount = state.plc.testcases.filter((testcase) => suggestionContextForTestcase(testcase.id).count > 0).length;
  dom.plc.testcaseFilterSummary.textContent = `${countLabel(visibleTestcases.length, 'testcase')} shown out of ${state.plc.testcases.length} · ${expectedFailCount} expected fail · ${savedSuggestionCount} with saved suggestions.`;

  if (!visibleTestcases.length) {
    dom.plc.testcaseList.className = 'stack-list empty';
    dom.plc.testcaseList.textContent = 'No testcases match the current filters.';
    return;
  }

  dom.plc.testcaseList.className = 'stack-list';
  dom.plc.testcaseList.innerHTML = visibleTestcases
    .map((testcase) => {
      const suggestionContext = suggestionContextForTestcase(testcase.id);
      return `
        <button type="button" class="list-card${testcase.id === state.plc.selectedTestcaseId ? ' active' : ''}" data-testcase-id="${escapeHtml(testcase.id)}">
          <div class="inline-meta">
            ${renderBadge(testcase.case_key)}
            ${renderBadge(`${testcase.input_type} → ${testcase.output_type}`)}
            ${renderStatusBadge(testcase.expected_outcome)}
            ${suggestionContext.latestStatus ? renderStatusBadge(suggestionContext.latestStatus) : renderBadge('no saved suggestion')}
          </div>
          <h3>${escapeHtml(testcase.instruction_name)}</h3>
          <p class="meta-line">row ${escapeHtml(testcase.source_row_number)} · case ${escapeHtml(testcase.source_case_index + 1)} · profile ${escapeHtml(testcase.execution_profile_key || 'n/a')}</p>
          <div class="badge-row">
            ${(testcase.tags || []).map(renderBadge).join('')}
            ${suggestionContext.count ? renderBadge(`${suggestionContext.count} suggestion${suggestionContext.count === 1 ? '' : 's'}`) : ''}
            ${suggestionContext.reviewRequired ? renderBadge('review required') : ''}
          </div>
        </button>
      `;
    })
    .join('');

  dom.plc.testcaseList.querySelectorAll('[data-testcase-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      state.plc.selectedTestcaseId = button.dataset.testcaseId;
      renderPlcTestcaseList();
      renderPlcTestcaseDetail();
      await Promise.all([refreshPlcNormalizationPreview(), refreshPlcSuggestions()]);
    });
  });
}

function renderPlcTestcaseDetail() {
  const testcase = selectedPlcTestcase();
  if (!testcase) {
    dom.plc.testcaseDetail.className = 'detail-stack empty';
    dom.plc.testcaseDetail.textContent = 'Select a testcase to inspect normalized inputs and expected outputs.';
    return;
  }

  const suggestionContext = suggestionContextForTestcase(testcase.id);
  const executionProfile = testcase.execution_profile || {};
  const fragments = [
    `<div class="inline-meta">${renderStatusBadge(testcase.expected_outcome)}${renderBadge(testcase.case_key)}${testcase.execution_profile_key ? renderBadge(`profile ${testcase.execution_profile_key}`) : ''}${suggestionContext.latestStatus ? renderStatusBadge(suggestionContext.latestStatus) : renderBadge('no saved suggestion')}</div>`,
    renderDetailGrid([
      { label: 'Testcase ID', value: testcase.id },
      { label: 'Case key', value: testcase.case_key },
      { label: 'Instruction', value: testcase.instruction_name },
      { label: 'Input type', value: testcase.input_type },
      { label: 'Output type', value: testcase.output_type },
      { label: 'Expected outcome', value: testcase.expected_outcome },
      { label: 'Timeout (ms)', value: testcase.timeout_ms },
      { label: 'Memory profile', value: testcase.memory_profile_key || '—' },
      { label: 'Execution profile', value: testcase.execution_profile_key || '—' },
    ]),
  ];

  fragments.push(`
    <section class="callout${suggestionContext.latestStatus === 'rejected' ? ' failure' : suggestionContext.latestStatus ? ' success' : ''}">
      <p class="callout-title">Suggestion review context</p>
      <div class="inline-meta">
        ${suggestionContext.latestStatus ? renderStatusBadge(suggestionContext.latestStatus) : renderBadge('no saved suggestion')}
        ${renderBadge(`${suggestionContext.count} saved suggestion${suggestionContext.count === 1 ? '' : 's'}`)}
        ${suggestionContext.reviewRequired ? renderBadge('review required') : ''}
      </div>
      <p>${escapeHtml(
        suggestionContext.latest
          ? `Latest suggestion ${suggestionContext.latest.id} was created ${formatDateTime(suggestionContext.latest.created_at)} and keeps the testcase in reviewer context before you drop into the saved suggestion slice below.`
          : 'Use the normalization preview below to create or review testcase-specific suggestions without leaving the testcase reviewer flow.',
      )}</p>
    </section>
  `);

  if (testcase.description) {
    fragments.push(`
      <section class="callout success">
        <p class="callout-title">Description</p>
        <p>${escapeHtml(testcase.description)}</p>
      </section>
    `);
  }

  fragments.push(
    renderDetailGrid([
      { label: 'Profile instruction', value: executionProfile.instruction_name || '—' },
      { label: 'Profile memory key', value: executionProfile.memory_profile_key || '—' },
      { label: 'Profile input type', value: executionProfile.input_type || '—' },
      { label: 'Profile output type', value: executionProfile.output_type || '—' },
    ]),
  );
  fragments.push(renderJsonCallout('Input vector', testcase.input_vector_json));
  fragments.push(renderJsonCallout('Expected output', testcase.expected_output_json));
  fragments.push(renderJsonCallout('Expanded expected outputs', testcase.expected_outputs_json));
  if (executionProfile && Object.keys(executionProfile).length) {
    fragments.push(renderJsonDetails('Execution profile payload', executionProfile));
  }

  dom.plc.testcaseDetail.className = 'detail-stack';
  dom.plc.testcaseDetail.innerHTML = fragments.join('');
}

function renderPlcNormalizationPanel() {
  const normalization = state.plc.normalization;
  const testcase = selectedPlcTestcase();
  const suggestionContext = testcase ? suggestionContextForTestcase(testcase.id) : null;
  dom.plc.normalizationPersistButton.disabled = !testcase || !normalization || Boolean(normalization.error);
  dom.plc.suggestionsRefresh.disabled = !testcase;
  if (!normalization) {
    dom.plc.normalizationPanel.className = 'detail-stack empty';
    dom.plc.normalizationPanel.textContent = 'Normalization suggestions will appear here.';
    return;
  }

  if (normalization.error) {
    dom.plc.normalizationPanel.className = 'detail-stack';
    dom.plc.normalizationPanel.innerHTML = `
      <section class="callout failure">
        <p class="callout-title">Normalization preview failed</p>
        <p>${escapeHtml(normalization.error)}</p>
      </section>
    `;
    return;
  }

  const warnings = Array.isArray(normalization.warnings) ? normalization.warnings : [];
  const normalizedCases = Array.isArray(normalization.normalized_cases) ? normalization.normalized_cases : [];
  const fragments = [
    `
      <section class="callout">
        <p class="callout-title">Normalization preview</p>
        <div class="inline-meta">
          ${renderBadge(normalization.suggestion_type || 'preview')}
          ${renderBadge(normalization.review_required ? 'review required' : 'review optional')}
          ${renderBadge(`${normalizedCases.length} normalized case${normalizedCases.length === 1 ? '' : 's'}`)}
        </div>
      </section>
    `,
  ];

  if (suggestionContext?.latest) {
    fragments.push(`
      <section class="callout ${suggestionContext.latestStatus === 'rejected' ? 'failure' : suggestionContext.latestStatus === 'accepted' ? 'success' : 'warning'}">
        <p class="callout-title">Saved suggestion status</p>
        <div class="inline-meta">
          ${renderStatusBadge(suggestionContext.latestStatus)}
          ${renderBadge(`suggestion ${suggestionContext.latest.id}`)}
          ${suggestionContext.reviewRequired ? renderBadge('review required') : ''}
        </div>
        <p>Latest saved suggestion created ${escapeHtml(formatDateTime(suggestionContext.latest.created_at))} so you can compare the live preview with the persisted review state.</p>
      </section>
    `);
  }

  if (normalization.persisted_suggestion) {
    fragments.push(`
      <section class="callout success">
        <p class="callout-title">Latest persisted suggestion</p>
        <div class="inline-meta">
          ${renderBadge(`suggestion ${normalization.persisted_suggestion.id}`)}
          ${renderStatusBadge(normalization.persisted_suggestion.status)}
          ${renderBadge(`saved ${formatDateTime(normalization.persisted_suggestion.created_at)}`)}
        </div>
      </section>
    `);
  }

  if (warnings.length) {
    fragments.push(renderDetailList('Preview warnings', warnings, 'warning'));
  }

  if (normalizedCases.length) {
    fragments.push(renderJsonCallout('Normalized cases', normalizedCases));
  }

  dom.plc.normalizationPanel.className = 'detail-stack';
  dom.plc.normalizationPanel.innerHTML = fragments.join('');
}

function renderPlcSuggestionList() {
  if (!selectedPlcTestcase()) {
    dom.plc.suggestionList.className = 'stack-list empty';
    dom.plc.suggestionList.textContent = 'Persisted suggestions will appear here after you select a testcase.';
    return;
  }

  if (!state.plc.suggestions.length) {
    dom.plc.suggestionList.className = 'stack-list empty';
    dom.plc.suggestionList.textContent = 'No persisted suggestions exist for this testcase yet.';
    return;
  }

  dom.plc.suggestionList.className = 'stack-list';
  dom.plc.suggestionList.innerHTML = state.plc.suggestions
    .map(
      (suggestion) => `
        <button type="button" class="list-card${suggestion.id === state.plc.selectedSuggestionId ? ' active' : ''}" data-suggestion-id="${escapeHtml(suggestion.id)}">
          <div class="inline-meta">
            ${renderStatusBadge(suggestion.status)}
            ${renderBadge(`suggestion ${suggestion.id}`)}
          </div>
          <h3>${escapeHtml(suggestion.suggestion_type || 'Normalization suggestion')}</h3>
          <p class="meta-line">created ${escapeHtml(formatDateTime(suggestion.created_at))}</p>
          <p class="meta-line">reviewed ${escapeHtml(formatDateTime(suggestion.reviewed_at))}</p>
        </button>
      `,
    )
    .join('');

  dom.plc.suggestionList.querySelectorAll('[data-suggestion-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadPlcSuggestion(button.dataset.suggestionId);
    });
  });
}

function renderPlcSuggestionDetail() {
  const suggestion = selectedPlcSuggestion();
  if (!suggestion) {
    dom.plc.suggestionDetail.className = 'detail-stack empty';
    dom.plc.suggestionDetail.textContent = 'Select a saved suggestion to inspect review state and payload detail.';
    return;
  }

  const suggestionPayload = suggestion.suggestion_payload_json || {};
  const warnings = Array.isArray(suggestionPayload.warnings) ? suggestionPayload.warnings : [];
  const normalizedCases = Array.isArray(suggestionPayload.normalized_cases) ? suggestionPayload.normalized_cases : [];
  dom.plc.suggestionDetail.className = 'detail-stack';
  dom.plc.suggestionDetail.innerHTML = `
    <div class="inline-meta">
      ${renderStatusBadge(suggestion.status)}
      ${renderBadge(`suggestion ${suggestion.id}`)}
      ${renderBadge(suggestion.suggestion_type || 'normalization')}
      ${renderBadge(suggestionPayload.review_required ? 'review required' : 'review optional')}
    </div>
    ${renderDetailGrid([
      { label: 'Created', value: formatDateTime(suggestion.created_at) },
      { label: 'Reviewed', value: formatDateTime(suggestion.reviewed_at) },
      { label: 'Suite ID', value: suggestion.suite_id || '—' },
      { label: 'Testcase ID', value: suggestion.testcase_id || '—' },
    ])}
    <div class="button-row">
      <button type="button" class="secondary-button" data-review-status="accepted" ${suggestion.status === 'accepted' ? 'disabled' : ''}>Mark accepted</button>
      <button type="button" class="secondary-button" data-review-status="rejected" ${suggestion.status === 'rejected' ? 'disabled' : ''}>Mark rejected</button>
    </div>
    ${warnings.length ? renderDetailList('Suggestion warnings', warnings, 'warning') : ''}
    ${renderJsonCallout('Source row', suggestion.source_payload_json?.raw_row || suggestion.source_payload_json || {})}
    ${renderJsonCallout('Suggested normalized cases', normalizedCases)}
  `;

  dom.plc.suggestionDetail.querySelectorAll('[data-review-status]').forEach((button) => {
    button.addEventListener('click', async () => {
      await reviewPlcSuggestion(button.dataset.reviewStatus);
    });
  });
}

function renderPlcRuns() {
  const visibleRuns = filteredPlcRuns();
  if (!state.plc.runs.length) {
    dom.plc.runFilterSummary.textContent = state.plc.selectedSuiteId ? 'No PLC runs found for the selected suite.' : 'Queued and completed PLC runs will appear here.';
    dom.plc.runList.className = 'stack-list empty';
    dom.plc.runList.textContent = state.plc.selectedSuiteId ? 'No PLC runs found for the selected suite.' : 'Queued and completed PLC runs will appear here.';
    return;
  }

  const backendFilters = [
    state.plc.selectedSuiteId ? `suite ${state.plc.selectedSuiteId}` : 'all suites',
    state.plc.filters.runTargetKey ? `target ${state.plc.filters.runTargetKey}` : null,
    state.plc.filters.runStatus ? `status ${state.plc.filters.runStatus}` : null,
    state.plc.filters.runProblemsOnly ? 'problem runs only' : null,
  ].filter(Boolean);
  dom.plc.runFilterSummary.textContent = `${countLabel(visibleRuns.length, 'run')} shown out of ${state.plc.runs.length} fetched for ${backendFilters.join(' · ')}.`;

  if (!visibleRuns.length) {
    dom.plc.runList.className = 'stack-list empty';
    dom.plc.runList.textContent = 'No runs match the current filters.';
    return;
  }

  dom.plc.runList.className = 'stack-list';
  dom.plc.runList.innerHTML = visibleRuns
    .map((run) => {
      const target = targetForKey(run.payload_json?.target_key || run.target_key);
      return `
        <button type="button" class="list-card plc-run-card${run.id === state.plc.selectedRunId ? ' active' : ''}${hasRunProblems(run) ? ' has-problem' : ''}" data-run-id="${escapeHtml(run.id)}">
          <div class="inline-meta">
            ${renderStatusBadge(run.status)}
            ${renderBadge(`job ${run.id}`)}
            ${run.payload_json?.target_key ? renderBadge(`target ${run.payload_json.target_key}`) : ''}
            ${target?.environment_label ? renderBadge(target.environment_label) : ''}
          </div>
          <h3>${escapeHtml(run.payload_json?.suite_title || run.plc_suite_id || 'PLC run')}</h3>
          <p class="meta-line">created ${escapeHtml(formatDateTime(run.created_at))} · ${escapeHtml(target?.display_name || target?.key || 'target metadata unavailable')}</p>
          <div class="badge-row">
            ${renderBadge(`queued ${run.summary?.queued_count ?? 0}`)}
            ${renderBadge(`running ${run.summary?.running_count ?? 0}`)}
            ${renderBadge(`pass ${run.summary?.passed_count ?? 0}`)}
            ${renderBadge(`fail ${run.summary?.failed_count ?? 0}`)}
            ${renderBadge(`error ${run.summary?.error_count ?? 0}`)}
            ${target?.line ? renderBadge(`line ${target.line}`) : ''}
            ${target?.bench ? renderBadge(`bench ${target.bench}`) : ''}
          </div>
        </button>
      `;
    })
    .join('');

  dom.plc.runList.querySelectorAll('[data-run-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      await loadPlcRun(button.dataset.runId);
    });
  });
}

function renderPlcRunSummary() {
  const run = state.plc.selectedRun;
  if (!run) {
    dom.plc.runLifecycle.className = 'run-lifecycle empty';
    dom.plc.runLifecycle.textContent = 'Select a PLC run to inspect queued, running, succeeded, and failed lifecycle state.';
    dom.plc.runSummary.className = 'detail-stack empty';
    dom.plc.runSummary.textContent = 'Select a PLC run to inspect pass/fail counts and testcase-level detail.';
    dom.plc.runItemFilterSummary.textContent = 'Run items will appear here after a PLC run starts.';
    dom.plc.runItemList.className = 'stack-list empty';
    dom.plc.runItemList.textContent = 'Run items will appear here after a PLC run starts.';
    dom.plc.runItemDetail.className = 'detail-stack empty';
    dom.plc.runItemDetail.textContent = 'Select a testcase result to inspect expected vs actual output, failure reason, raw I/O snippets, and executor logs.';
    return;
  }

  const payload = run.payload_json || {};
  const result = run.result_json || {};
  const targetSnapshot = payload.target_snapshot || targetForKey(payload.target_key || run.target_key) || {};
  const targetMetadata = targetSnapshot.metadata_json || {};
  const requestedCases = safeArray(payload.testcases);
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  dom.plc.runLifecycle.className = 'run-lifecycle';
  dom.plc.runLifecycle.innerHTML = renderRunLifecycle(run.status);
  const fragments = [
    `<div class="inline-meta">${renderStatusBadge(run.status)}${renderBadge(`suite ${run.plc_suite_id || '—'}`)}${renderBadge(`target ${payload.target_key || run.target_key || 'stub-local'}`)}${targetSnapshot.environment_label ? renderBadge(targetSnapshot.environment_label) : ''}</div>`,
    renderDetailGrid([
      { label: 'Run ID', value: run.id },
      { label: 'Suite title', value: payload.suite_title || run.plc_suite_id || '—' },
      { label: 'Target display', value: targetSnapshot.display_name || targetSnapshot.key || '—' },
      { label: 'Target environment', value: targetSnapshot.environment_label || '—' },
      { label: 'Line', value: targetSnapshot.line || targetMetadata.line || '—' },
      { label: 'Bench', value: targetSnapshot.bench || targetMetadata.bench || '—' },
      { label: 'Executor mode', value: result.executor_mode || '—' },
      { label: 'Validator version', value: result.validator_version || '—' },
      { label: 'Requested cases', value: requestedCases.length || run.summary?.total_count || 0 },
      { label: 'Created', value: formatDateTime(run.created_at) },
      { label: 'Started', value: formatDateTime(run.started_at) },
      { label: 'Finished', value: formatDateTime(run.finished_at) },
      { label: 'Attempts', value: `${run.attempts}/${run.max_attempts}` },
    ]),
    `
      <section class="callout ${hasRunProblems(run) ? 'failure' : 'success'}">
        <p class="callout-title">Run review summary</p>
        <div class="inline-meta">
          ${renderBadge(`${run.summary?.total_count ?? 0} total items`)}
          ${renderBadge(`${run.summary?.passed_count ?? 0} passed`)}
          ${renderBadge(`${run.summary?.failed_count ?? 0} failed`)}
          ${renderBadge(`${run.summary?.error_count ?? 0} errors`)}
        </div>
        <p>${escapeHtml(
          hasRunProblems(run)
            ? 'This run needs reviewer attention because at least one testcase failed validation or the executor reported an error condition.'
            : 'This run completed without recorded testcase failures, so the drill-down can focus on confirming expected behavior and trace coverage.',
        )}</p>
      </section>
    `,
    `
      <section class="status-summary">
        <article class="stat-card">
          <p class="stat-label">Queued</p>
          <p class="stat-value">${escapeHtml(run.summary?.queued_count ?? 0)}</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">Running</p>
          <p class="stat-value">${escapeHtml(run.summary?.running_count ?? 0)}</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">Total</p>
          <p class="stat-value">${escapeHtml(run.summary?.total_count ?? 0)}</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">Passed</p>
          <p class="stat-value">${escapeHtml(run.summary?.passed_count ?? 0)}</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">Failed</p>
          <p class="stat-value">${escapeHtml(run.summary?.failed_count ?? 0)}</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">Errors</p>
          <p class="stat-value">${escapeHtml(run.summary?.error_count ?? 0)}</p>
        </article>
      </section>
    `,
  ];

  fragments.push(`
    <section class="callout">
      <p class="callout-title">Target context</p>
      <div class="badge-row">
        ${safeArray(targetSnapshot.tags || targetMetadata.tags).map(renderBadge).join('') || '<span class="meta-line">No target tags</span>'}
      </div>
      <p class="detail-copy">${escapeHtml(targetSnapshot.description || 'Run target metadata is shown here so reviewers can confirm the environment, line, and bench before interpreting failures.')}</p>
    </section>
  `);

  if (run.error) {
    fragments.push(`
      <section class="callout failure">
        <p class="callout-title">Run error</p>
        <p>${escapeHtml(run.error)}</p>
      </section>
    `);
  }

  if (warnings.length) {
    fragments.push(renderDetailList('Run warnings', warnings, 'warning'));
  }

  if (requestedCases.length) {
    fragments.push(renderJsonDetails('Run request testcases', requestedCases, { summaryDetail: `${requestedCases.length} queued case payloads` }));
  }

  if (Object.keys(payload).length) {
    fragments.push(renderJsonDetails('Full run payload', payload));
  }

  dom.plc.runSummary.className = 'detail-stack';
  dom.plc.runSummary.innerHTML = fragments.join('');
  renderPlcRunItemList();
  renderPlcRunItemDetail();
}

function renderPlcRunItemList() {
  const visibleItems = filteredPlcRunItems();
  if (!state.plc.runItems.length) {
    dom.plc.runItemFilterSummary.textContent = ACTIVE_JOB_STATUSES.has(state.plc.selectedRun?.status) ? 'Waiting for testcase results...' : 'No testcase-level results are available for this run yet.';
    dom.plc.runItemList.className = 'stack-list empty';
    dom.plc.runItemList.textContent = ACTIVE_JOB_STATUSES.has(state.plc.selectedRun?.status) ? 'Waiting for testcase results...' : 'No testcase-level results are available for this run yet.';
    return;
  }

  dom.plc.runItemFilterSummary.textContent = `${countLabel(visibleItems.length, 'run item')} shown out of ${state.plc.runItems.length}.`;

  if (!visibleItems.length) {
    dom.plc.runItemList.className = 'stack-list empty';
    dom.plc.runItemList.textContent = 'No run items match the current filters.';
    return;
  }

  dom.plc.runItemList.className = 'stack-list';
  dom.plc.runItemList.innerHTML = visibleItems
    .map((item) => {
      const requestContext = item.request_context_json || {};
      const targetContext = requestContext.target_context || {};
      return `
        <button type="button" class="list-card plc-run-item-card${item.id === state.plc.selectedRunItemId ? ' active' : ''}${hasRunItemProblems(item) ? ' has-problem' : ''}" data-run-item-id="${escapeHtml(item.id)}">
          <div class="inline-meta">
            ${renderStatusBadge(item.status)}
            ${renderBadge(item.case_key)}
            ${renderBadge(item.expected_outcome || 'unknown outcome')}
          </div>
          <h3>${escapeHtml(item.instruction_name)}</h3>
          <p class="meta-line">duration ${escapeHtml(item.duration_ms)} ms · testcase ${escapeHtml(item.testcase_id)}</p>
          <div class="badge-row">
            ${renderBadge(`${item.input_type} → ${item.output_type}`)}
            ${item.execution_profile_key ? renderBadge(`profile ${item.execution_profile_key}`) : ''}
            ${targetContext.environment_label ? renderBadge(targetContext.environment_label) : ''}
          </div>
          ${item.failure_reason ? `<p class="meta-line">${escapeHtml(item.failure_reason)}</p>` : ''}
        </button>
      `;
    })
    .join('');

  dom.plc.runItemList.querySelectorAll('[data-run-item-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.plc.selectedRunItemId = button.dataset.runItemId;
      renderPlcRunItemList();
      renderPlcRunItemDetail();
    });
  });
}

function renderPlcRunItemDetail() {
  const item = selectedPlcRunItem();
  if (!item) {
    dom.plc.runItemDetail.className = 'detail-stack empty';
    dom.plc.runItemDetail.textContent = 'Select a testcase result to inspect expected vs actual output, failure reason, raw I/O snippets, and executor logs.';
    return;
  }

  const validatorResult = item.validator_result_json || {};
  const requestContext = item.request_context_json || {};
  const runContext = requestContext.run_context || {};
  const testcaseContext = requestContext.testcase_context || {};
  const targetContext = requestContext.target_context || {};
  const executionProfile = requestContext.execution_profile || {};
  const diagnostics = Array.isArray(validatorResult.diagnostics) ? validatorResult.diagnostics : [];
  const mismatches = Array.isArray(validatorResult.mismatches) ? validatorResult.mismatches : [];
  const fragments = [
    `<div class="inline-meta">${renderStatusBadge(item.status)}${renderBadge(item.case_key)}${renderBadge(`${item.duration_ms} ms`)}${targetContext.environment_label ? renderBadge(targetContext.environment_label) : ''}</div>`,
    renderDetailGrid([
      { label: 'Item ID', value: item.id },
      { label: 'Testcase ID', value: item.testcase_id },
      { label: 'Instruction', value: item.instruction_name },
      { label: 'Input type', value: item.input_type || '—' },
      { label: 'Output type', value: item.output_type || '—' },
      { label: 'Expected outcome', value: item.expected_outcome || '—' },
      { label: 'Execution profile', value: item.execution_profile_key || '—' },
      { label: 'Validator', value: validatorResult.validator || '—' },
      { label: 'Validator status', value: validatorResult.status || '—' },
      { label: 'Mismatch count', value: mismatches.length },
      { label: 'Type mismatch', value: validatorResult.type_mismatch ? 'yes' : 'no' },
      { label: 'Started', value: formatDateTime(item.started_at) },
      { label: 'Finished', value: formatDateTime(item.finished_at) },
    ]),
    `
      <section class="callout ${hasRunItemProblems(item) ? 'failure' : 'success'}">
        <p class="callout-title">Expected vs actual review</p>
        <p>${escapeHtml(
          hasRunItemProblems(item)
            ? 'The executor completed this testcase with a validation problem. Compare the requested inputs, expected output, actual output, and validator diagnostics below before deciding whether the issue is data, target, or execution behavior.'
            : 'This testcase passed validation. Use the trace below to confirm the request context, I/O order, and validator payload all line up with the intended execution profile.',
        )}</p>
      </section>
    `,
    `
      <section class="comparison-grid">
        ${renderComparisonSection('Input vector', item.inputs_json)}
        ${renderComparisonSection('Expected output', item.expected_output_json)}
        ${renderComparisonSection('Actual output', item.actual_output_json)}
      </section>
    `,
  ];

  if (item.failure_reason) {
    fragments.push(`
      <section class="callout ${item.status === 'passed' ? 'success' : 'failure'}">
        <p class="callout-title">${item.status === 'passed' ? 'Validation note' : 'Failure reason'}</p>
        <p>${escapeHtml(item.failure_reason)}</p>
      </section>
    `);
  }

  if (diagnostics.length) {
    fragments.push(renderDetailList('Validator diagnostics', diagnostics, item.status === 'passed' ? 'success' : 'warning'));
  }

  if (mismatches.length) {
    fragments.push(renderJsonDetails('Validator mismatches', mismatches, { open: true, summaryDetail: `${mismatches.length} mismatch entries` }));
  }

  fragments.push(
    renderDetailGrid([
      { label: 'Run ID', value: runContext.run_id || '—' },
      { label: 'Suite ID', value: runContext.suite_id || '—' },
      { label: 'Suite title', value: runContext.suite_title || '—' },
      { label: 'Source row', value: testcaseContext.source_row_number ?? '—' },
      { label: 'Source case index', value: testcaseContext.source_case_index ?? '—' },
      { label: 'Target key', value: targetContext.key || '—' },
      { label: 'Target name', value: targetContext.display_name || '—' },
      { label: 'Target environment', value: targetContext.environment_label || '—' },
      { label: 'Target mode', value: targetContext.executor_mode || '—' },
    ]),
  );

  if (testcaseContext.description || safeArray(testcaseContext.tags).length) {
    fragments.push(`
      <section class="callout">
        <p class="callout-title">Testcase context</p>
        ${testcaseContext.description ? `<p>${escapeHtml(testcaseContext.description)}</p>` : ''}
        <div class="badge-row">${safeArray(testcaseContext.tags).map(renderBadge).join('') || '<span class="meta-line">No testcase tags</span>'}</div>
      </section>
    `);
  }

  if (safeArray(targetContext.tags).length) {
    fragments.push(`
      <section class="callout">
        <p class="callout-title">Target tags</p>
        <div class="badge-row">${safeArray(targetContext.tags).map(renderBadge).join('')}</div>
      </section>
    `);
  }

  if (Object.keys(executionProfile).length) {
    fragments.push(
      renderDetailGrid([
        { label: 'Profile key', value: executionProfile.key || item.execution_profile_key || '—' },
        { label: 'Profile instruction', value: executionProfile.instruction_name || '—' },
        { label: 'Profile memory key', value: executionProfile.memory_profile_key || '—' },
        { label: 'Profile input type', value: executionProfile.input_type || '—' },
        { label: 'Profile output type', value: executionProfile.output_type || '—' },
      ]),
    );
    fragments.push(renderJsonDetails('Execution profile payload', executionProfile));
  }

  fragments.push(renderJsonDetails('Validator payload', validatorResult, { summaryDetail: 'Full rule-based validation envelope' }));
  fragments.push(renderJsonDetails('Request context payload', requestContext, { summaryDetail: 'Run, testcase, target, and execution profile context' }));

  if (Array.isArray(item.io_logs) && item.io_logs.length) {
    fragments.push(renderIoLogList(item.io_logs));
  }

  if (item.executor_log) {
    fragments.push(renderTextLog('Executor log', item.executor_log));
  }

  dom.plc.runItemDetail.className = 'detail-stack';
  dom.plc.runItemDetail.innerHTML = fragments.join('');
}

async function fetchPlcDashboardSummary() {
  return fetchJson(buildUrl('/plc-dashboard/summary', { suite_id: currentPlcDashboardSuiteId() }));
}

async function refreshPlcDashboard() {
  state.plc.summary = await fetchPlcDashboardSummary();
  renderPlcDashboard();
}

async function refreshPlcTargets() {
  const requestToken = ++state.plc.requestTokens.targets;
  const targets = await fetchJson('/plc-targets');
  if (requestToken !== state.plc.requestTokens.targets) {
    return;
  }
  state.plc.targets = Array.isArray(targets) ? targets : [];
  const activeTarget = state.plc.targets.find((target) => target.key === state.plc.selectedTargetKey && target.is_active);
  if (!activeTarget) {
    state.plc.selectedTargetKey = state.plc.targets.find((target) => target.is_active)?.key || state.plc.targets[0]?.key || 'stub-local';
  }
  renderPlcTargets();
}

async function ensurePlcInitialized({ force = false } = {}) {
  if (state.plc.hasLoadedInitialData && !force) {
    return;
  }

  await Promise.all([refreshPlcDashboard(), refreshPlcTargets(), refreshPlcSuites()]);
  state.plc.hasLoadedInitialData = true;
}

async function fetchPlcRuns() {
  return fetchJson(
    buildUrl('/plc-test-runs', {
      suite_id: state.plc.selectedSuiteId,
      target_key: state.plc.filters.runTargetKey,
      status: state.plc.filters.runStatus,
      failed_only: state.plc.filters.runProblemsOnly,
    }),
  );
}

async function refreshPlcSuiteSuggestionContext() {
  if (!state.plc.selectedSuiteId) {
    state.plc.suiteSuggestions = [];
    renderPlcSuiteDetail();
    renderPlcTestcaseFilters();
    renderPlcTestcaseList();
    renderPlcTestcaseDetail();
    return;
  }

  const suiteId = state.plc.selectedSuiteId;
  const requestToken = ++state.plc.requestTokens.suiteSuggestions;
  const suggestions = await fetchJson(buildUrl('/plc-llm/suggestions', { suite_id: suiteId }));
  if (requestToken !== state.plc.requestTokens.suiteSuggestions || state.plc.selectedSuiteId !== suiteId) {
    return;
  }
  state.plc.suiteSuggestions = Array.isArray(suggestions) ? suggestions : [];
  renderPlcSuiteDetail();
  renderPlcTestcaseFilters();
  renderPlcTestcaseList();
  renderPlcTestcaseDetail();
}

function clearPlcSelections() {
  state.plc.selectedSuiteId = null;
  state.plc.selectedSuite = null;
  state.plc.summary = null;
  state.plc.testcases = [];
  state.plc.suiteSuggestions = [];
  state.plc.selectedTestcaseId = null;
  state.plc.normalization = null;
  state.plc.suggestions = [];
  state.plc.selectedSuggestionId = null;
  state.plc.selectedSuggestion = null;
  state.plc.runs = [];
  state.plc.selectedRunId = null;
  state.plc.selectedRun = null;
  state.plc.runItems = [];
  state.plc.selectedRunItemId = null;
  stopPlcRunPolling();
  renderPlcDashboard();
  renderPlcSuiteDetail();
  renderPlcTestcaseFilters();
  renderPlcTestcaseList();
  renderPlcTestcaseDetail();
  renderPlcNormalizationPanel();
  renderPlcSuggestionList();
  renderPlcSuggestionDetail();
  renderPlcRuns();
  renderPlcRunSummary();
}

async function refreshPlcSuites({ preferredSuiteId = null } = {}) {
  state.plc.suites = await fetchJson('/plc-test-suites');
  const nextSuiteId = preferredSuiteId && state.plc.suites.some((suite) => suite.id === preferredSuiteId)
    ? preferredSuiteId
    : state.plc.suites.some((suite) => suite.id === state.plc.selectedSuiteId)
      ? state.plc.selectedSuiteId
      : state.plc.suites[0]?.id || null;

  state.plc.selectedSuiteId = nextSuiteId;
  renderPlcSuites();

  if (!nextSuiteId) {
    clearPlcSelections();
    return;
  }

  await loadPlcSuite(nextSuiteId, { preserveTestcase: true });
}

async function loadPlcSuite(suiteId, { preserveTestcase = false } = {}) {
  if (!suiteId) {
    clearPlcSelections();
    return;
  }

  const requestToken = ++state.plc.requestTokens.suite;

  const [suite, testcases] = await Promise.all([
    fetchJson(`/plc-test-suites/${encodeURIComponent(suiteId)}`),
    fetchJson(buildUrl('/plc-testcases', { suite_id: suiteId })),
  ]);

  if (requestToken !== state.plc.requestTokens.suite) {
    return;
  }

  state.plc.selectedSuiteId = suiteId;
  state.plc.selectedSuite = suite;
  state.plc.testcases = Array.isArray(testcases) ? testcases : [];
  if (!preserveTestcase || !state.plc.testcases.some((testcase) => testcase.id === state.plc.selectedTestcaseId)) {
    state.plc.selectedTestcaseId = state.plc.testcases[0]?.id || null;
  }

  renderPlcSuites();
  renderPlcSuiteDetail();
  renderPlcTestcaseFilters();
  renderPlcTestcaseList();
  renderPlcTestcaseDetail();
  await Promise.all([refreshPlcDashboard(), refreshPlcSuiteSuggestionContext(), refreshPlcNormalizationPreview(), refreshPlcSuggestions(), refreshPlcRuns()]);
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

async function refreshPlcNormalizationPreview() {
  const testcase = selectedPlcTestcase();
  if (!testcase) {
    state.plc.normalization = null;
    renderPlcNormalizationPanel();
    return;
  }

  const testcaseId = testcase.id;
  const requestToken = ++state.plc.requestTokens.normalization;
  try {
    const normalization = await fetchJson('/plc-llm/suggest-testcase-normalization', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_row: testcaseToNormalizationRow(testcase) }),
    });
    if (state.plc.selectedTestcaseId !== testcaseId || requestToken !== state.plc.requestTokens.normalization) {
      return;
    }
    state.plc.normalization = normalization;
  } catch (error) {
    if (state.plc.selectedTestcaseId !== testcaseId || requestToken !== state.plc.requestTokens.normalization) {
      return;
    }
    state.plc.normalization = { error: error.message };
  }
  renderPlcNormalizationPanel();
}

async function refreshPlcSuggestions({ preferredSuggestionId = null } = {}) {
  const testcase = selectedPlcTestcase();
  if (!testcase || !state.plc.selectedSuiteId) {
    state.plc.suggestions = [];
    state.plc.selectedSuggestionId = null;
    state.plc.selectedSuggestion = null;
    renderPlcSuggestionList();
    renderPlcSuggestionDetail();
    return;
  }

  const testcaseId = testcase.id;
  const requestToken = ++state.plc.requestTokens.suggestions;
  const suggestions = await fetchJson(
    buildUrl('/plc-llm/suggestions', {
      suite_id: state.plc.selectedSuiteId,
      testcase_id: testcaseId,
    }),
  );
  if (requestToken !== state.plc.requestTokens.suggestions || state.plc.selectedTestcaseId !== testcaseId) {
    return;
  }

  state.plc.suggestions = Array.isArray(suggestions) ? suggestions : [];
  state.plc.selectedSuggestionId = preferredSuggestionId && state.plc.suggestions.some((suggestion) => String(suggestion.id) === String(preferredSuggestionId))
    ? preferredSuggestionId
    : state.plc.suggestions.some((suggestion) => String(suggestion.id) === String(state.plc.selectedSuggestionId))
      ? state.plc.selectedSuggestionId
      : state.plc.suggestions[0]?.id || null;

  renderPlcSuggestionList();

  if (!state.plc.selectedSuggestionId) {
    state.plc.selectedSuggestion = null;
    renderPlcSuggestionDetail();
    return;
  }

  await loadPlcSuggestion(state.plc.selectedSuggestionId);
}

async function loadPlcSuggestion(suggestionId) {
  if (!suggestionId) {
    state.plc.selectedSuggestionId = null;
    state.plc.selectedSuggestion = null;
    renderPlcSuggestionList();
    renderPlcSuggestionDetail();
    return;
  }

  const testcaseId = state.plc.selectedTestcaseId;
  const requestToken = ++state.plc.requestTokens.suggestionDetail;
  const suggestion = await fetchJson(`/plc-llm/suggestions/${encodeURIComponent(suggestionId)}`);
  if (requestToken !== state.plc.requestTokens.suggestionDetail || state.plc.selectedTestcaseId !== testcaseId) {
    return;
  }
  state.plc.selectedSuggestionId = suggestion.id;
  state.plc.selectedSuggestion = suggestion;
  renderPlcSuggestionList();
  renderPlcSuggestionDetail();
}

async function reviewPlcSuggestion(status) {
  const suggestion = selectedPlcSuggestion();
  if (!suggestion) {
    setPlcRunHint('Select a saved suggestion before changing its review status.');
    return;
  }

  try {
    const reviewed = await fetchJson(`/plc-llm/suggestions/${encodeURIComponent(suggestion.id)}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await Promise.all([
      refreshPlcSuiteSuggestionContext(),
      refreshPlcSuggestions({ preferredSuggestionId: reviewed.id }),
    ]);
    setPlcRunHint(`Suggestion ${reviewed.id} marked ${reviewed.status}.`);
  } catch (error) {
    setPlcRunHint(error.message);
  }
}

async function refreshPlcRuns() {
  state.plc.runs = await fetchPlcRuns();
  if (!state.plc.runs.some((run) => run.id === state.plc.selectedRunId)) {
    state.plc.selectedRunId = state.plc.runs[0]?.id || null;
  }
  renderPlcRuns();

  if (!state.plc.selectedRunId) {
    state.plc.selectedRun = null;
    state.plc.runItems = [];
    state.plc.selectedRunItemId = null;
    stopPlcRunPolling();
    renderPlcRunSummary();
    return;
  }

  await loadPlcRun(state.plc.selectedRunId, { preserveItem: true });
}

async function loadPlcRun(runId, { preserveItem = false } = {}) {
  if (!runId) {
    state.plc.selectedRun = null;
    state.plc.runItems = [];
    state.plc.selectedRunItemId = null;
    stopPlcRunPolling();
    renderPlcRunSummary();
    return;
  }

  const requestToken = ++state.plc.requestTokens.run;

  const [run, items] = await Promise.all([
    fetchJson(`/plc-test-runs/${encodeURIComponent(runId)}`),
    fetchJson(`/plc-test-runs/${encodeURIComponent(runId)}/items`),
  ]);

  if (requestToken !== state.plc.requestTokens.run) {
    return;
  }

  state.plc.selectedRunId = runId;
  state.plc.selectedRun = run;
  state.plc.runItems = Array.isArray(items) ? items : [];
  if (!preserveItem || !state.plc.runItems.some((item) => item.id === state.plc.selectedRunItemId)) {
    state.plc.selectedRunItemId = state.plc.runItems[0]?.id || null;
  }

  renderPlcRuns();
  renderPlcRunSummary();

  if (ACTIVE_JOB_STATUSES.has(run.status)) {
    beginPlcRunPolling(runId);
  } else {
    stopPlcRunPolling();
  }
}

function beginPlcRunPolling(runId) {
  if (state.plc.pollRunId === runId && state.plc.pollHandle) {
    return;
  }

  stopPlcRunPolling();
  state.plc.pollRunId = runId;
  state.plc.pollHandle = window.setInterval(async () => {
    try {
    const [run, items, runs, summary] = await Promise.all([
      fetchJson(`/plc-test-runs/${encodeURIComponent(runId)}`),
      fetchJson(`/plc-test-runs/${encodeURIComponent(runId)}/items`),
      fetchPlcRuns(),
      fetchPlcDashboardSummary(),
    ]);

      state.plc.selectedRun = run;
      state.plc.runItems = Array.isArray(items) ? items : [];
      state.plc.runs = Array.isArray(runs) ? runs : [];
      state.plc.summary = summary;
      if (!state.plc.runItems.some((item) => item.id === state.plc.selectedRunItemId)) {
        state.plc.selectedRunItemId = state.plc.runItems[0]?.id || null;
      }

      renderPlcDashboard();
      renderPlcRuns();
      renderPlcRunSummary();

      if (TERMINAL_JOB_STATUSES.has(run.status)) {
        stopPlcRunPolling();
        dom.plc.runButton.disabled = false;
        setPlcRunHint(run.status === 'succeeded' ? `PLC run ${run.id} completed.` : `PLC run ${run.id} failed: ${run.error || 'unknown error'}`);
      }
    } catch (error) {
      stopPlcRunPolling();
      dom.plc.runButton.disabled = false;
      setPlcRunHint(error.message);
    }
  }, 1500);
}

dom.modeButtons.forEach((button) => {
  button.addEventListener('click', async () => {
    try {
      await setMode(button.dataset.mode);
      if (button.dataset.mode === MODES.PLC) {
        setPlcRunHint('PLC tester ready. Import a suite or inspect existing runs.');
      }
    } catch (error) {
      if (button.dataset.mode === MODES.PLC) {
        setPlcRunHint(error.message);
      } else {
        setWorkflowHint(error.message);
      }
    }
  });
});

dom.workflow.runButton.addEventListener('click', async () => {
  const prompt = dom.workflow.promptInput.value.trim();
  if (!state.workflow.selectedWorkflowKey) {
    setWorkflowHint('Select a workflow first.');
    return;
  }
  if (!state.workflow.selectedDatasetKey) {
    setWorkflowHint('Select a dataset first.');
    return;
  }
  if (!prompt) {
    setWorkflowHint('Enter a prompt before running the workflow.');
    return;
  }

  dom.workflow.runButton.disabled = true;
  dom.workflow.resultPanel.className = 'result-panel empty';
  dom.workflow.resultPanel.textContent = 'Workflow queued…';
  dom.workflow.evidencePanel.className = 'evidence-list empty';
  dom.workflow.evidencePanel.textContent = 'Evidence will appear after completion.';
  setWorkflowHint('Submitting workflow job...');

  try {
    const queued = await fetchJson(`/workflows/${state.workflow.selectedWorkflowKey}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        dataset_key: state.workflow.selectedDatasetKey,
        k: 4,
      }),
    });
    renderWorkflowJob(queued);
    setWorkflowHint(`Job ${queued.job_id} queued. Polling for status...`);
    beginWorkflowPolling(queued.job_id);
  } catch (error) {
    dom.workflow.runButton.disabled = false;
    setWorkflowHint(error.message);
  }
});

dom.workflow.datasetSelect.addEventListener('change', async (event) => {
  const nextKey = event.target.value;
  state.workflow.selectedDatasetKey = nextKey;
  try {
    await activateDataset(nextKey);
    setWorkflowHint(`Active dataset switched to ${nextKey}.`);
  } catch (error) {
    setWorkflowHint(error.message);
  }
});

dom.plc.summaryRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
    await Promise.all([refreshPlcDashboard(), refreshPlcTargets()]);
    setPlcRunHint(`PLC dashboard refreshed for ${dashboardScopeSummary().label}.`);
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.summaryScopeSelect.addEventListener('change', async (event) => {
  state.plc.dashboardScope = event.target.value;
  renderPlcDashboard();
  try {
    await ensurePlcInitialized();
    await refreshPlcDashboard();
    setPlcRunHint(`PLC dashboard scope switched to ${dashboardScopeSummary().label}.`);
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.targetSelect.addEventListener('change', (event) => {
  state.plc.selectedTargetKey = event.target.value;
  renderPlcTargets();
  const target = selectedPlcTarget();
  setPlcRunHint(target ? `PLC target set to ${target.display_name || target.key}.` : 'PLC target selection updated.');
});

dom.plc.testcaseFilterInput.addEventListener('input', (event) => {
  state.plc.filters.testcaseQuery = event.target.value;
  renderPlcTestcaseList();
});

dom.plc.testcaseInstructionFilter.addEventListener('change', (event) => {
  state.plc.filters.testcaseInstruction = event.target.value;
  renderPlcTestcaseList();
});

dom.plc.testcaseInputTypeFilter.addEventListener('change', (event) => {
  state.plc.filters.testcaseInputType = event.target.value;
  renderPlcTestcaseList();
});

dom.plc.testcaseOutcomeFilter.addEventListener('change', (event) => {
  state.plc.filters.testcaseOutcome = event.target.value;
  renderPlcTestcaseList();
});

dom.plc.testcaseSuggestionFilter.addEventListener('change', (event) => {
  state.plc.filters.testcaseSuggestionStatus = event.target.value;
  renderPlcTestcaseList();
});

dom.plc.importButton.addEventListener('click', async () => {
  const file = dom.plc.importFile.files[0];
  if (!file) {
    setPlcImportHint('Choose a CSV or XLSX file before importing.');
    return;
  }

  dom.plc.importButton.disabled = true;
  setPlcImportHint('Uploading PLC suite...');

  const formData = new FormData();
  formData.append('file', file);
  if (dom.plc.importTitle.value.trim()) {
    formData.append('title', dom.plc.importTitle.value.trim());
  }

  try {
    const imported = await fetchJson('/plc-testcases/import', {
      method: 'POST',
      body: formData,
    });
    state.plc.hasLoadedInitialData = true;
    dom.plc.importFile.value = '';
    await Promise.all([
      refreshPlcDashboard(),
      refreshPlcSuites({ preferredSuiteId: imported.suite_id }),
    ]);
    setPlcImportHint(`Imported ${imported.imported_count} testcase${imported.imported_count === 1 ? '' : 's'} into ${imported.title}. Rejected ${imported.rejected_count}.`);
    setPlcRunHint(`Suite ${imported.suite_id} is ready to review or run.`);
  } catch (error) {
    setPlcImportHint(error.message);
  } finally {
    dom.plc.importButton.disabled = false;
  }
});

dom.plc.suitesRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
    await refreshPlcSuites();
    setPlcRunHint('PLC suites refreshed.');
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.normalizationRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
    await Promise.all([refreshPlcNormalizationPreview(), refreshPlcSuggestions()]);
    setPlcRunHint('Normalization preview refreshed.');
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.normalizationPersistButton.addEventListener('click', async () => {
  const testcase = selectedPlcTestcase();
  if (!testcase) {
    setPlcRunHint('Select a testcase before persisting a suggestion.');
    return;
  }

  dom.plc.normalizationPersistButton.disabled = true;
  setPlcRunHint(`Persisting normalization suggestion for ${testcase.case_key}...`);
  try {
    const normalization = await fetchJson('/plc-llm/suggest-testcase-normalization', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suite_id: state.plc.selectedSuiteId,
        testcase_id: testcase.id,
        persist: true,
        raw_row: testcaseToNormalizationRow(testcase),
      }),
    });
    state.plc.normalization = normalization;
    renderPlcNormalizationPanel();
    await Promise.all([
      refreshPlcSuiteSuggestionContext(),
      refreshPlcSuggestions({ preferredSuggestionId: normalization.persisted_suggestion?.id || null }),
    ]);
    setPlcRunHint(`Persisted suggestion ${normalization.persisted_suggestion?.id || ''} for ${testcase.case_key}.`.trim());
  } catch (error) {
    setPlcRunHint(error.message);
    renderPlcNormalizationPanel();
  }
});

dom.plc.suggestionsRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
    await Promise.all([
      refreshPlcSuiteSuggestionContext(),
      refreshPlcSuggestions({ preferredSuggestionId: state.plc.selectedSuggestionId }),
    ]);
    setPlcRunHint('Saved suggestions refreshed.');
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.runFilterInput.addEventListener('input', (event) => {
  state.plc.filters.runQuery = event.target.value;
  renderPlcRuns();
});

dom.plc.runTargetFilter.addEventListener('change', async (event) => {
  state.plc.filters.runTargetKey = event.target.value;
  try {
    await refreshPlcRuns();
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.runStatusFilter.addEventListener('change', async (event) => {
  state.plc.filters.runStatus = event.target.value;
  try {
    await refreshPlcRuns();
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.runProblemsOnly.addEventListener('change', async (event) => {
  state.plc.filters.runProblemsOnly = event.target.checked;
  try {
    await refreshPlcRuns();
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.runButton.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
  } catch (error) {
    setPlcRunHint(error.message);
    return;
  }

  if (!state.plc.selectedSuiteId) {
    setPlcRunHint('Select a PLC suite before enqueueing a run.');
    return;
  }

  const targetKey = state.plc.selectedTargetKey || dom.plc.targetSelect.value || 'stub-local';
  const runSelectedOnly = dom.plc.runSelectedOnly.checked;
  const testcase = selectedPlcTestcase();
  if (runSelectedOnly && !testcase) {
    setPlcRunHint('Pick a testcase before running a testcase-scoped PLC job.');
    return;
  }

  dom.plc.runButton.disabled = true;
  setPlcRunHint('Enqueueing PLC run...');

  try {
    const queued = await fetchJson('/plc-test-runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suite_id: state.plc.selectedSuiteId,
        testcase_ids: runSelectedOnly && testcase ? [testcase.id] : [],
        target_key: targetKey,
      }),
    });
    await Promise.all([refreshPlcDashboard(), refreshPlcRuns()]);
    setPlcRunHint(`PLC run ${queued.job_id} queued for ${queued.suite_title}. Polling for status...`);
    await loadPlcRun(queued.job_id);
  } catch (error) {
    dom.plc.runButton.disabled = false;
    setPlcRunHint(error.message);
  }
});

dom.plc.runsRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
    await Promise.all([refreshPlcRuns(), refreshPlcTargets()]);
    setPlcRunHint('PLC runs refreshed.');
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

dom.plc.runItemFilterInput.addEventListener('input', (event) => {
  state.plc.filters.itemQuery = event.target.value;
  renderPlcRunItemList();
});

dom.plc.runItemStatusFilter.addEventListener('change', (event) => {
  state.plc.filters.itemStatus = event.target.value;
  renderPlcRunItemList();
});

dom.plc.runItemProblemsOnly.addEventListener('change', (event) => {
  state.plc.filters.itemProblemsOnly = event.target.checked;
  renderPlcRunItemList();
});

dom.plc.runDetailRefresh.addEventListener('click', async () => {
  try {
    await ensurePlcInitialized();
  } catch (error) {
    setPlcRunHint(error.message);
    return;
  }

  if (!state.plc.selectedRunId) {
    setPlcRunHint('Select a PLC run before refreshing detail.');
    return;
  }
  try {
    await Promise.all([refreshPlcDashboard(), loadPlcRun(state.plc.selectedRunId, { preserveItem: true })]);
    setPlcRunHint(`PLC run ${state.plc.selectedRunId} refreshed.`);
  } catch (error) {
    setPlcRunHint(error.message);
  }
});

async function boot() {
  renderMode();
  try {
    await Promise.all([refreshWorkflowDatasets(), refreshWorkflowCatalog()]);
    setWorkflowHint('Ready. Choose a dataset, select a workflow, and run the demo.');
    setPlcImportHint('Choose a CSV or XLSX file to import PLC testcases.');
    setPlcRunHint('Switch to PLC testing mode to load suites, review testcases, and enqueue runs.');
  } catch (error) {
    setWorkflowHint(error.message);
  }
}

boot();

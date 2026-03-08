const state = {
  datasets: [],
  workflows: [],
  selectedDatasetKey: null,
  selectedWorkflowKey: null,
  pollHandle: null,
};

const datasetSelect = document.querySelector('#dataset-select');
const workflowList = document.querySelector('#workflow-list');
const promptInput = document.querySelector('#prompt-input');
const runButton = document.querySelector('#run-button');
const runHint = document.querySelector('#run-hint');
const jobStatus = document.querySelector('#job-status');
const resultPanel = document.querySelector('#result-panel');
const evidencePanel = document.querySelector('#evidence-panel');

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || `Request failed: ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function setHint(message) {
  runHint.textContent = message || '';
}

function renderDatasets() {
  datasetSelect.innerHTML = '';
  state.datasets.forEach((dataset) => {
    const option = document.createElement('option');
    option.value = dataset.key;
    option.textContent = `${dataset.title}${dataset.is_active ? ' (active)' : ''}`;
    if (dataset.key === state.selectedDatasetKey) {
      option.selected = true;
    }
    datasetSelect.append(option);
  });
}

function renderWorkflows() {
  workflowList.innerHTML = '';
  state.workflows.forEach((workflow) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `workflow-card${workflow.key === state.selectedWorkflowKey ? ' active' : ''}`;
    button.innerHTML = `<h3>${workflow.title}</h3><p>${workflow.summary}</p>`;
    button.addEventListener('click', () => {
      state.selectedWorkflowKey = workflow.key;
      renderWorkflows();
      promptInput.placeholder = workflow.prompt_label;
    });
    workflowList.append(button);
  });
}

function renderJob(job) {
  jobStatus.textContent = JSON.stringify(job, null, 2);
  jobStatus.classList.remove('empty');
}

function renderResult(job) {
  const result = job.result_json || null;
  if (!result) {
    resultPanel.className = 'result-panel empty';
    resultPanel.textContent = job.status === 'failed' ? `Workflow failed: ${job.error || 'unknown error'}` : 'Waiting for result payload.';
    return;
  }

  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  const fragments = [];
  if (result.summary) {
    fragments.push(`<section class="result-group"><h3>Summary</h3><p>${escapeHtml(result.summary)}</p></section>`);
  }
  if (Array.isArray(result.key_points)) {
    fragments.push(renderListGroup('Key points', result.key_points));
  }
  if (Array.isArray(result.recommendations)) {
    fragments.push(renderListGroup('Recommendations', result.recommendations));
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
    fragments.push(renderListGroup('Findings', result.findings));
  }
  if (Array.isArray(result.actions)) {
    fragments.push(renderListGroup('Actions', result.actions));
  }
  if (!fragments.length) {
    fragments.push(`<pre class="json-block">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`);
  }

  resultPanel.className = 'result-panel';
  resultPanel.innerHTML = fragments.join('');

  evidencePanel.className = evidence.length ? 'evidence-list' : 'evidence-list empty';
  evidencePanel.innerHTML = evidence.length
    ? evidence.map(renderEvidenceCard).join('')
    : 'No evidence returned.';
}

function renderListGroup(label, items) {
  return `<section class="result-group"><h3>${label}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></section>`;
}

function renderEvidenceCard(item) {
  return `
    <article class="evidence-card">
      <h3>${escapeHtml(item.title || item.source_path)}</h3>
      <p class="evidence-meta">chunk=${escapeHtml(item.chunk_id)} · source=${escapeHtml(item.source_path)} · score=${Number(item.score).toFixed(6)}</p>
      <p>${escapeHtml(item.text)}</p>
    </article>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function refreshDatasets() {
  state.datasets = await fetchJson('/datasets');
  const active = state.datasets.find((dataset) => dataset.is_active) || state.datasets[0];
  state.selectedDatasetKey = active ? active.key : null;
  renderDatasets();
}

async function refreshWorkflows() {
  state.workflows = await fetchJson('/workflows');
  state.selectedWorkflowKey = state.selectedWorkflowKey || state.workflows[0]?.key || null;
  renderWorkflows();
  const selected = state.workflows.find((workflow) => workflow.key === state.selectedWorkflowKey);
  if (selected) {
    promptInput.placeholder = selected.prompt_label;
  }
}

async function pollJob(jobId) {
  clearInterval(state.pollHandle);
  state.pollHandle = setInterval(async () => {
    try {
      const job = await fetchJson(`/jobs/${jobId}`);
      renderJob(job);
      renderResult(job);
      if (job.status === 'succeeded' || job.status === 'failed') {
        clearInterval(state.pollHandle);
        state.pollHandle = null;
        runButton.disabled = false;
        setHint(job.status === 'succeeded' ? 'Workflow completed.' : `Workflow failed: ${job.error || 'unknown error'}`);
      }
    } catch (error) {
      clearInterval(state.pollHandle);
      state.pollHandle = null;
      runButton.disabled = false;
      setHint(error.message);
    }
  }, 1200);
}

async function activateDataset(datasetKey) {
  await fetchJson('/datasets/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_key: datasetKey }),
  });
  await refreshDatasets();
}

runButton.addEventListener('click', async () => {
  const prompt = promptInput.value.trim();
  if (!state.selectedWorkflowKey) {
    setHint('Select a workflow first.');
    return;
  }
  if (!state.selectedDatasetKey) {
    setHint('Select a dataset first.');
    return;
  }
  if (!prompt) {
    setHint('Enter a prompt before running the workflow.');
    return;
  }

  runButton.disabled = true;
  resultPanel.className = 'result-panel empty';
  resultPanel.textContent = 'Workflow queued…';
  evidencePanel.className = 'evidence-list empty';
  evidencePanel.textContent = 'Evidence will appear after completion.';
  setHint('Submitting workflow job...');

  try {
    const queued = await fetchJson(`/workflows/${state.selectedWorkflowKey}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        dataset_key: state.selectedDatasetKey,
        k: 4,
      }),
    });
    renderJob(queued);
    setHint(`Job ${queued.job_id} queued. Polling for status...`);
    await pollJob(queued.job_id);
  } catch (error) {
    runButton.disabled = false;
    setHint(error.message);
  }
});

datasetSelect.addEventListener('change', async (event) => {
  const nextKey = event.target.value;
  state.selectedDatasetKey = nextKey;
  try {
    await activateDataset(nextKey);
    setHint(`Active dataset switched to ${nextKey}.`);
  } catch (error) {
    setHint(error.message);
  }
});

async function boot() {
  try {
    await Promise.all([refreshDatasets(), refreshWorkflows()]);
    setHint('Ready. Choose a dataset, select a workflow, and run the demo.');
  } catch (error) {
    setHint(error.message);
  }
}

boot();

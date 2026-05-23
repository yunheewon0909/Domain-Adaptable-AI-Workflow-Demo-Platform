'use strict';

const state = {
  collections: [],
  selectedCollectionId: null,
  models: [],
  selectedModelId: null,
  training: { jobId: null, datasetVersionId: null, polling: false },
  chat: { messages: [] },
};

const $ = (id) => document.getElementById(id);

const dom = {
  kbSelect: $('kb-select'),
  kbNewName: $('kb-new-name'),
  kbNewButton: $('kb-new-button'),
  kbDeleteCollection: $('kb-delete-collection'),
  kbFile: $('kb-file'),
  kbUploadButton: $('kb-upload-button'),
  kbDocs: $('kb-docs'),
  kbHint: $('kb-hint'),
  trainPairs: $('train-pairs'),
  trainMaxChunks: $('train-max-chunks'),
  trainBase: $('train-base'),
  trainStart: $('train-start'),
  trainStatus: $('train-status'),
  trainStepper: $('train-stepper'),
  trainLogsWrap: $('train-logs-wrap'),
  trainLogs: $('train-logs'),
  chatModel: $('chat-model'),
  chatGround: $('chat-ground'),
  chatLog: $('chat-log'),
  chatForm: $('chat-form'),
  chatInput: $('chat-input'),
  chatClear: $('chat-clear'),
  chatSuggestions: $('chat-suggestions'),
  settingsStatus: $('settings-status'),
};

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!response.ok) {
    const message = body && body.detail ? JSON.stringify(body.detail) : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderMarkdown(value) {
  // Minimal Markdown: code fences, inline code, **bold**, *italic*.
  // Everything else falls back to pre-wrap line preservation in CSS.
  const escaped = escapeHtml(value);
  const blocks = [];
  let withBlocks = escaped.replace(/```([\s\S]*?)```/g, (_, body) => {
    blocks.push(body.replace(/^\n/, ''));
    return `CODEBLOCK${blocks.length - 1}`;
  });
  withBlocks = withBlocks.replace(/`([^`\n]+?)`/g, '<code>$1</code>');
  withBlocks = withBlocks.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>');
  withBlocks = withBlocks.replace(/(^|[\s(])\*([^*\n]+?)\*(?=[\s).,!?]|$)/g, '$1<em>$2</em>');
  withBlocks = withBlocks.replace(/CODEBLOCK(\d+)/g, (_, idx) => {
    return `<pre class="mdpre"><code>${blocks[Number(idx)]}</code></pre>`;
  });
  return withBlocks;
}

function setKbHint(msg) {
  dom.kbHint.textContent = msg || '';
}

const TRAIN_PHASE_ORDER = [
  'generating',
  'preparing_data',
  'training',
  'packaging',
  'registering',
  'succeeded',
];

function setTrainStatus(msg) {
  dom.trainStatus.textContent = msg || 'Idle.';
}

function setTrainStep(phase, { failed = false } = {}) {
  if (!dom.trainStepper) return;
  dom.trainStepper.classList.toggle('hidden', !phase);
  const steps = dom.trainStepper.querySelectorAll('.step');
  if (!phase) {
    steps.forEach((s) => s.classList.remove('active', 'done', 'failed'));
    return;
  }
  const targetIdx = TRAIN_PHASE_ORDER.indexOf(phase);
  steps.forEach((step) => {
    const stepPhase = step.getAttribute('data-phase');
    const stepIdx = TRAIN_PHASE_ORDER.indexOf(stepPhase);
    step.classList.remove('active', 'done', 'failed');
    if (failed && stepIdx === targetIdx) {
      step.classList.add('failed');
    } else if (stepIdx < targetIdx) {
      step.classList.add('done');
    } else if (stepIdx === targetIdx) {
      step.classList.add('active');
    }
  });
}

function selectedCollection() {
  return state.collections.find((c) => c.id === state.selectedCollectionId) || null;
}

// ---- knowledge base ---------------------------------------------------------

async function refreshCollections({ preferredId = null } = {}) {
  state.collections = await fetchJson('/rag-collections');
  const next =
    preferredId ||
    state.selectedCollectionId ||
    (state.collections[0] && state.collections[0].id) ||
    null;
  state.selectedCollectionId = next && state.collections.some((c) => c.id === next) ? next : null;
  renderKbSelect();
  await renderKbDocs();
}

function renderKbSelect() {
  if (!state.collections.length) {
    dom.kbSelect.innerHTML = '<option value="">— no collections yet —</option>';
    dom.kbSelect.value = '';
    return;
  }
  dom.kbSelect.innerHTML = state.collections
    .map((c) => {
      const count = typeof c.document_count === 'number' ? c.document_count : 0;
      const label = `${c.name} (${count} doc${count === 1 ? '' : 's'})`;
      return `<option value="${escapeHtml(c.id)}">${escapeHtml(label)}</option>`;
    })
    .join('');
  if (state.selectedCollectionId) {
    dom.kbSelect.value = state.selectedCollectionId;
  }
}

async function renderKbDocs() {
  const collection = selectedCollection();
  if (!collection) {
    dom.kbDocs.textContent = 'No collection selected.';
    return;
  }
  try {
    const docs = await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}/documents`);
    if (!docs.length) {
      dom.kbDocs.innerHTML = `<span class="text-muted-fg">Collection <strong>${escapeHtml(
        collection.name,
      )}</strong> has no documents yet.</span>`;
      return;
    }
    dom.kbDocs.innerHTML =
      `<div class="text-muted-fg mb-1">${escapeHtml(collection.name)} · ${docs.length} document(s)</div>` +
      '<ul class="space-y-1">' +
      docs
        .map(
          (d) => `
            <li class="flex items-center justify-between gap-2">
              <span class="truncate">${escapeHtml(d.filename || d.id)}</span>
              <button data-doc-id="${escapeHtml(d.id)}" class="kb-doc-delete text-xs text-muted-fg hover:text-fg underline">delete</button>
            </li>`,
        )
        .join('') +
      '</ul>';
    dom.kbDocs.querySelectorAll('.kb-doc-delete').forEach((btn) => {
      btn.addEventListener('click', async (event) => {
        const id = event.currentTarget.getAttribute('data-doc-id');
        if (!id) return;
        try {
          await fetchJson(`/rag-documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
          setKbHint(`Deleted document ${id}.`);
          await renderKbDocs();
        } catch (error) {
          setKbHint(error.message);
        }
      });
    });
  } catch (error) {
    dom.kbDocs.textContent = `Failed to load documents: ${error.message}`;
  }
}

dom.kbSelect.addEventListener('change', async (event) => {
  state.selectedCollectionId = event.target.value || null;
  await renderKbDocs();
  renderChatSuggestions();
});

dom.kbDeleteCollection.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setKbHint('Select a collection to delete.');
    return;
  }
  if (!window.confirm(`Delete collection "${collection.name}" and all its documents? This cannot be undone.`)) {
    return;
  }
  dom.kbDeleteCollection.disabled = true;
  try {
    await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}`, { method: 'DELETE' });
    state.selectedCollectionId = null;
    setKbHint(`Deleted collection ${collection.name}.`);
    await refreshCollections();
  } catch (error) {
    setKbHint(error.message);
  } finally {
    dom.kbDeleteCollection.disabled = false;
  }
});

dom.kbNewButton.addEventListener('click', async () => {
  const name = dom.kbNewName.value.trim();
  if (!name) {
    setKbHint('Enter a collection name first.');
    return;
  }
  dom.kbNewButton.disabled = true;
  try {
    const created = await fetchJson('/rag-collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    dom.kbNewName.value = '';
    setKbHint(`Created collection ${created.name}.`);
    await refreshCollections({ preferredId: created.id });
  } catch (error) {
    setKbHint(error.message);
  } finally {
    dom.kbNewButton.disabled = false;
  }
});

dom.kbUploadButton.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setKbHint('Select or create a collection first.');
    return;
  }
  const files = Array.from(dom.kbFile.files || []);
  if (!files.length) {
    setKbHint('Pick at least one file to upload.');
    return;
  }
  dom.kbUploadButton.disabled = true;
  setKbHint(`Uploading ${files.length} file(s)…`);
  try {
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}/documents`, {
        method: 'POST',
        body: form,
      });
    }
    setKbHint(`Uploaded ${files.length} file(s).`);
    dom.kbFile.value = '';
    await renderKbDocs();
  } catch (error) {
    setKbHint(error.message);
  } finally {
    dom.kbUploadButton.disabled = false;
  }
});

// ---- train ------------------------------------------------------------------

async function refreshTrainingLogs() {
  if (!state.training.jobId || !dom.trainLogs || !dom.trainLogsWrap) return;
  try {
    const response = await fetch(`/ft-training-jobs/${encodeURIComponent(state.training.jobId)}/logs`);
    if (!response.ok) return;
    const text = await response.text();
    // Prefer the live `log_tail` (subprocess stdout) when present; fall
    // back to the static `log_text` (DB column with the queued message
    // or the final summary).
    let body = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object') {
        body =
          (typeof parsed.log_tail === 'string' && parsed.log_tail) ||
          (typeof parsed.log_text === 'string' && parsed.log_text) ||
          text;
      }
    } catch {
      /* plain text */
    }
    const tail = body.split('\n').slice(-120).join('\n');
    dom.trainLogs.textContent = tail || '(no log output yet)';
    dom.trainLogsWrap.classList.remove('hidden');
  } catch {
    /* swallow log fetch errors; main poll still drives status */
  }
}

async function pollTrainingJob() {
  if (!state.training.jobId) return;
  state.training.polling = true;
  while (state.training.polling && state.training.jobId) {
    try {
      const job = await fetchJson(`/ft-training-jobs/${encodeURIComponent(state.training.jobId)}`);
      const status = job.status || 'unknown';
      const phase = job.phase || status;
      setTrainStatus(`Training job ${job.id}: ${status}${phase && phase !== status ? ` (${phase})` : ''}`);
      if (TRAIN_PHASE_ORDER.includes(phase)) {
        setTrainStep(phase);
      }
      await refreshTrainingLogs();
      if (status === 'succeeded' || status === 'failed') {
        if (status === 'succeeded') {
          setTrainStep('succeeded');
          try {
            await fetchJson(`/ft-training-jobs/${encodeURIComponent(state.training.jobId)}/publish`, { method: 'POST' });
            setTrainStatus(`Job ${job.id} ${status}. Model registered. Load it in LM Studio to make it selectable in chat.`);
          } catch (err) {
            setTrainStatus(`Job ${job.id} ${status}. Publish step warned: ${err.message}`);
          }
        } else {
          setTrainStep(phase, { failed: true });
          setTrainStatus(`Job ${job.id} ${status}. ${(job.error_json && job.error_json.user_message) || job.error || ''}`);
        }
        await refreshModels();
        break;
      }
    } catch (error) {
      setTrainStatus(`Polling error: ${error.message}`);
      break;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  state.training.polling = false;
}

dom.trainStart.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setTrainStatus('Pick a collection in step 1 first.');
    return;
  }
  if (!collection.document_count) {
    setTrainStatus(`Collection "${collection.name}" has no documents. Upload at least one before training.`);
    return;
  }
  const pairs = Math.max(1, Math.min(10, Number(dom.trainPairs.value) || 3));
  const maxChunks = Math.max(1, Math.min(200, Number(dom.trainMaxChunks.value) || 20));
  const base = dom.trainBase.value.trim() || 'qwen3.5-4b-mlx';
  dom.trainStart.disabled = true;
  setTrainStep('generating');
  setTrainStatus('Generating Q/A pairs from collection…');
  try {
    const built = await fetchJson('/ft-datasets/from-rag-collection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rag_collection_id: collection.id,
        dataset_name: `${collection.name} dataset`,
        max_chunks: maxChunks,
        pairs_per_chunk: pairs,
      }),
    });
    const versionId = built.dataset_version_id;
    state.training.datasetVersionId = versionId;
    setTrainStatus(`Generated ${built.row_count} Q/A rows. Locking dataset version…`);

    await fetchJson(`/ft-dataset-versions/${encodeURIComponent(versionId)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'validated' }),
    });
    await fetchJson(`/ft-dataset-versions/${encodeURIComponent(versionId)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'locked' }),
    });
    setTrainStatus('Dataset locked. Enqueueing training job…');

    const job = await fetchJson('/ft-training-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_version_id: versionId,
        base_model_name: base,
        training_method: 'sft_qlora',
      }),
    });
    state.training.jobId = job.id;
    setTrainStatus(`Training job ${job.id} queued. Polling…`);
    pollTrainingJob();
  } catch (error) {
    setTrainStatus(error.message);
  } finally {
    dom.trainStart.disabled = false;
  }
});

// ---- models -----------------------------------------------------------------

async function refreshModels() {
  try {
    const reply = await fetchJson('/v1/models');
    state.models = (reply && reply.data) || [];
  } catch {
    state.models = [];
  }
  if (!state.models.length) {
    dom.chatModel.innerHTML = '<option value="">— no selectable models —</option>';
    state.selectedModelId = null;
    return;
  }
  dom.chatModel.innerHTML = state.models
    .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.id)}</option>`)
    .join('');
  if (!state.selectedModelId || !state.models.some((m) => m.id === state.selectedModelId)) {
    state.selectedModelId = state.models[0].id;
  }
  dom.chatModel.value = state.selectedModelId;
  renderChatSuggestions();
}

dom.chatModel.addEventListener('change', (event) => {
  state.selectedModelId = event.target.value || null;
});

const CHAT_SUGGESTIONS = [
  'Summarize this knowledge base in 3 bullet points.',
  'What are the main topics covered?',
  'List specific facts or numbers mentioned in the docs.',
  'What is the most important thing a new reader should know?',
];

function renderChatSuggestions() {
  if (!dom.chatSuggestions) return;
  const collection = selectedCollection();
  const hasModel = !!state.selectedModelId;
  if (!collection || !hasModel) {
    dom.chatSuggestions.innerHTML = collection
      ? '<span class="text-muted-fg">Load a model in LM Studio to start chatting.</span>'
      : '<span class="text-muted-fg">Pick a collection in step 1 to enable grounded chat.</span>';
    return;
  }
  dom.chatSuggestions.innerHTML = CHAT_SUGGESTIONS.map(
    (s) =>
      `<button type="button" data-suggestion="${escapeHtml(s)}" class="suggestion rounded-full border border-border px-3 py-1 hover:bg-muted">${escapeHtml(s)}</button>`,
  ).join('');
  dom.chatSuggestions.querySelectorAll('.suggestion').forEach((btn) => {
    btn.addEventListener('click', (event) => {
      const text = event.currentTarget.getAttribute('data-suggestion') || '';
      dom.chatInput.value = text;
      dom.chatInput.focus();
    });
  });
}

// ---- chat -------------------------------------------------------------------

function renderChat() {
  if (!state.chat.messages.length) {
    dom.chatLog.innerHTML = '<p class="text-muted-fg">No messages yet. Ask something to get started.</p>';
    return;
  }
  dom.chatLog.innerHTML = state.chat.messages
    .map((m) => {
      const sources =
        m.sources && m.sources.length
          ? `<div class="sources">Grounded in: ${m.sources.map((s) => escapeHtml(s)).join(', ')}</div>`
          : '';
      const body = m.role === 'assistant' ? renderMarkdown(m.content) : escapeHtml(m.content);
      return `
        <div class="msg ${m.role}">
          <div class="role">${escapeHtml(m.role)}</div>
          <div class="body">${body}</div>
          ${sources}
        </div>
      `;
    })
    .join('');
  dom.chatLog.scrollTop = dom.chatLog.scrollHeight;
}

dom.chatClear.addEventListener('click', () => {
  state.chat.messages = [];
  renderChat();
});

dom.chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.selectedModelId) {
    state.chat.messages.push({
      role: 'assistant',
      content: 'No model selected. Load a model in LM Studio first.',
    });
    renderChat();
    return;
  }
  const text = dom.chatInput.value.trim();
  if (!text) return;
  // Push the user turn AND a placeholder assistant turn so reviewers see
  // immediate feedback while Qwen3-style thinking takes 10-30s. Tag the
  // placeholder with a unique token so we can find (and skip) it later
  // if the user pressed Clear or sent another message before the reply
  // landed.
  const requestToken = Symbol('chat-request');
  state.chat.messages.push({ role: 'user', content: text });
  state.chat.messages.push({
    role: 'assistant',
    content: '…thinking',
    pending: requestToken,
  });
  renderChat();
  dom.chatInput.value = '';
  const submitButton = dom.chatForm.querySelector('button[type="submit"]');
  if (submitButton) submitButton.disabled = true;
  dom.chatInput.disabled = true;

  const body = {
    model: state.selectedModelId,
    messages: state.chat.messages
      .slice(0, -1) // drop the placeholder we just pushed
      .map(({ role, content }) => ({ role, content })),
    max_tokens: 4096,
  };
  const groundedCollection = selectedCollection();
  if (dom.chatGround.checked && groundedCollection) {
    body.rag_collection_id = groundedCollection.id;
    body.top_k = 4;
  }

  const replaceByToken = (replacement) => {
    const idx = state.chat.messages.findIndex((m) => m.pending === requestToken);
    if (idx >= 0) state.chat.messages[idx] = replacement;
  };

  try {
    const reply = await fetchJson('/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const answer =
      reply.choices && reply.choices[0] && reply.choices[0].message && reply.choices[0].message.content;
    const sources = (
      (reply.x_domain_platform &&
        reply.x_domain_platform.retrieval_preview &&
        reply.x_domain_platform.retrieval_preview.results) ||
      []
    )
      .map((r) => r.filename)
      .filter(Boolean);
    replaceByToken({
      role: 'assistant',
      content: answer || '(no content returned)',
      sources,
    });
  } catch (error) {
    replaceByToken({
      role: 'assistant',
      content: `Error: ${error.message}`,
    });
  } finally {
    if (submitButton) submitButton.disabled = false;
    dom.chatInput.disabled = false;
    dom.chatInput.focus();
  }
  renderChat();
});

// ---- settings ---------------------------------------------------------------

async function refreshStatus() {
  const lines = [];
  try {
    const health = await fetchJson('/health');
    lines.push(`API: ${health.status || 'ok'}`);
  } catch (e) {
    lines.push(`API: unreachable (${e.message})`);
  }
  try {
    const models = await fetchJson('/v1/models');
    lines.push(`Selectable models: ${(models.data || []).length}`);
  } catch {
    lines.push('Selectable models: unknown');
  }
  lines.push(`Active collection: ${state.selectedCollectionId || '(none)'}`);
  dom.settingsStatus.innerHTML = lines.map((l) => `<div>${escapeHtml(l)}</div>`).join('');
}

// ---- boot -------------------------------------------------------------------

async function boot() {
  renderChat();
  await refreshCollections();
  await refreshModels();
  await refreshStatus();
}

boot().catch((error) => {
  console.error('boot failed', error);
  setKbHint(`Boot failed: ${error.message}`);
});

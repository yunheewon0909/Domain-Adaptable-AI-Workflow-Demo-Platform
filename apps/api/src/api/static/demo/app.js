'use strict';

const state = {
  collections: [],
  selectedCollectionId: null,
  models: [],
  selectedModelId: null,
  training: { jobId: null, datasetVersionId: null, polling: false },
  qa: { pairs: [], versionId: null },
  chat: { messages: [] },
  ftModels: [],
};

const $ = (id) => document.getElementById(id);

const dom = {
  kbSelect: $('kb-select'),
  kbNewName: $('kb-new-name'),
  kbNewButton: $('kb-new-button'),
  kbReveal: $('kb-reveal'),
  kbRenameCollection: $('kb-rename-collection'),
  kbDeleteCollection: $('kb-delete-collection'),
  kbFile: $('kb-file'),
  kbUploadButton: $('kb-upload-button'),
  kbNewDocButton: $('kb-new-doc-button'),
  kbNewDocForm: $('kb-new-doc-form'),
  kbTextName: $('kb-text-name'),
  kbTextContent: $('kb-text-content'),
  kbTextSave: $('kb-text-save'),
  kbTextCancel: $('kb-text-cancel'),
  kbDocs: $('kb-docs'),
  kbHint: $('kb-hint'),
  trainPairs: $('train-pairs'),
  trainMaxChunks: $('train-max-chunks'),
  trainBase: $('train-base'),
  trainQaModel: $('train-qa-model'),
  generateQaBtn: $('generate-qa-btn'),
  generateQaStatus: $('generate-qa-status'),
  qaReviewSection: $('qa-review-section'),
  qaPairsList: $('qa-pairs-list'),
  qaPairCount: $('qa-pair-count'),
  addPairBtn: $('add-pair-btn'),
  finetuneSection: $('finetune-section'),
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
  verifyJudgeModel: $('verify-judge-model'),
  verifyFtModel: $('verify-ft-model'),
  verifyBaseModel: $('verify-base-model'),
  verifyQuestion: $('verify-question'),
  verifySuggestBtn: $('verify-suggest-btn'),
  verifySuggestHint: $('verify-suggest-hint'),
  verifyRunBtn: $('verify-run-btn'),
  verifyStatus: $('verify-status'),
  verifyProgress: $('verify-progress'),
  verifyLogWrap: $('verify-log-wrap'),
  verifyLog: $('verify-log'),
  verifyResults: $('verify-results'),
  verifyResultsBody: $('verify-results-body'),
  ftManageList: $('ft-manage-list'),
};

async function fetchJson(path, options = {}) {
  const { timeoutMs = 0, ...fetchOpts } = options;
  const controller = timeoutMs > 0 ? new AbortController() : null;
  if (controller) {
    fetchOpts.signal = controller.signal;
    setTimeout(() => controller.abort(), timeoutMs);
  }
  const response = await fetch(path, fetchOpts);
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

const loadedDocContent = new Set();

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
  loadedDocContent.clear();
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
      `<div class="text-muted-fg mb-2">${escapeHtml(collection.name)} · ${docs.length} document(s)</div>` +
      '<ul class="space-y-3">' +
      docs
        .map(
          (d) => `
            <li class="rounded-lg border border-border bg-muted/20 p-3">
              <div class="flex items-center gap-2 cursor-pointer" data-doc-toggle="${escapeHtml(d.id)}">
                <span class="font-medium text-sm break-all flex-1">${escapeHtml(d.filename || d.id)}</span>
                <span class="text-xs text-muted-fg">(${d.preview_length || 0}b)</span>
              </div>
              <div class="kb-doc-expand hidden mt-3 space-y-2" data-doc-expand="${escapeHtml(d.id)}">
                <input class="kb-doc-name-input w-full rounded-md border border-border bg-card px-3 py-2 text-sm" value="${escapeHtml(d.filename || d.id)}" data-doc-id="${escapeHtml(d.id)}" />
                <textarea class="kb-doc-content-textarea w-full rounded-md border border-border bg-card px-3 py-2 text-sm font-mono resize-y" rows="8" data-doc-id="${escapeHtml(d.id)}">...loading...</textarea>
                <div class="flex justify-between items-center">
                  <button class="kb-doc-delete-btn rounded-md border border-destructive/40 bg-card px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 hover:border-destructive transition-colors min-h-[40px]" data-doc-id="${escapeHtml(d.id)}">🗑 Delete</button>
                  <div class="flex gap-2">
                    <button class="kb-doc-save-btn rounded-md bg-accent text-accent-fg px-3 py-2 text-sm font-medium hover:opacity-90 min-h-[40px]" data-doc-id="${escapeHtml(d.id)}">💾 Save</button>
                    <button class="kb-doc-cancel-btn rounded-md border border-border px-3 py-2 text-sm hover:bg-muted min-h-[40px]" data-doc-id="${escapeHtml(d.id)}">✖ Cancel</button>
                  </div>
                </div>
              </div>
            </li>`,
        )
        .join('') +
      '</ul>';

    dom.kbDocs.querySelectorAll('[data-doc-toggle]').forEach((row) => {
      row.addEventListener('click', async () => {
        const id = row.getAttribute('data-doc-toggle');
        if (!id) return;
        const expand = dom.kbDocs.querySelector(`[data-doc-expand="${CSS.escape(id)}"]`);
        if (!expand) return;
        const isHidden = expand.classList.contains('hidden');
        expand.classList.toggle('hidden', !isHidden);
        if (isHidden && !loadedDocContent.has(id)) {
          const textarea = expand.querySelector('.kb-doc-content-textarea');
          if (textarea) {
            try {
              const payload = await fetchJson(`/rag-documents/${encodeURIComponent(id)}/content`);
              textarea.value = payload.encoding === 'base64'
                ? '[binary content — cannot edit inline]'
                : (payload.content || '');
              loadedDocContent.add(id);
            } catch (error) {
              textarea.value = `Failed to load content: ${error.message}`;
            }
          }
        }
      });
    });

    dom.kbDocs.querySelectorAll('.kb-doc-save-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-doc-id');
        if (!id) return;
        if (!window.confirm('Save changes to this document?')) return;
        const expand = dom.kbDocs.querySelector(`[data-doc-expand="${CSS.escape(id)}"]`);
        if (!expand) return;
        const nameInput = expand.querySelector('.kb-doc-name-input');
        const textarea = expand.querySelector('.kb-doc-content-textarea');
        btn.disabled = true;
        try {
          await fetchJson(`/rag-documents/${encodeURIComponent(id)}/content`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: textarea ? textarea.value : '' }),
          });
          if (nameInput && nameInput.value.trim()) {
            await fetchJson(`/rag-documents/${encodeURIComponent(id)}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ filename: nameInput.value.trim() }),
            });
          }
          setKbHint('Document saved.');
          await renderKbDocs();
        } catch (error) {
          setKbHint(error.message);
          btn.disabled = false;
        }
      });
    });

    dom.kbDocs.querySelectorAll('.kb-doc-delete-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-doc-id');
        if (!id) return;
        if (!window.confirm('Permanently delete this document? This cannot be undone.')) return;
        try {
          await fetchJson(`/rag-documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
          setKbHint('Document deleted.');
          await renderKbDocs();
        } catch (error) {
          setKbHint(error.message);
        }
      });
    });

    dom.kbDocs.querySelectorAll('.kb-doc-cancel-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-doc-id');
        if (!id) return;
        await renderKbDocs();
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

dom.kbReveal.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setKbHint('Pick a collection first.');
    return;
  }
  try {
    const r = await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}/reveal`, {
      method: 'POST',
    });
    setKbHint(`Opened ${r.opened} in Finder.`);
  } catch (error) {
    setKbHint(error.message);
  }
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

dom.kbRenameCollection.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setKbHint('Select a collection to rename.');
    return;
  }
  const newName = window.prompt(`Rename collection to:`, collection.name);
  if (!newName || !newName.trim() || newName.trim() === collection.name) return;
  try {
    await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.trim() }),
    });
    setKbHint(`Renamed to "${newName.trim()}".`);
    await refreshCollections({ preferredId: collection.id });
  } catch (error) {
    setKbHint(error.message);
  }
});

dom.kbNewDocButton.addEventListener('click', () => {
  dom.kbNewDocForm.classList.toggle('hidden');
  if (!dom.kbNewDocForm.classList.contains('hidden')) {
    dom.kbTextName.focus();
  }
});

dom.kbTextCancel.addEventListener('click', () => {
  dom.kbNewDocForm.classList.add('hidden');
});

dom.kbTextSave.addEventListener('click', async () => {
  const collection = selectedCollection();
  if (!collection) {
    setKbHint('Select or create a collection first.');
    return;
  }
  const filename = dom.kbTextName.value.trim() || 'document.txt';
  const content = dom.kbTextContent.value;
  if (!content.trim()) {
    setKbHint('Document content cannot be empty.');
    return;
  }
  dom.kbTextSave.disabled = true;
  try {
    const created = await fetchJson(`/rag-collections/${encodeURIComponent(collection.id)}/documents/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, content }),
    });
    setKbHint(`Saved "${filename}" to ${collection.name}.`);
    dom.kbTextName.value = '';
    dom.kbTextContent.value = '';
    dom.kbNewDocForm.classList.add('hidden');
    await renderKbDocs();
    if (created && created.id) {
      const expand = dom.kbDocs.querySelector(`[data-doc-expand="${CSS.escape(created.id)}"]`);
      if (expand) {
        expand.classList.remove('hidden');
        const textarea = expand.querySelector('.kb-doc-content-textarea');
        if (textarea) {
          textarea.value = content;
          loadedDocContent.add(created.id);
        }
      }
    }
  } catch (error) {
    setKbHint(error.message);
  } finally {
    dom.kbTextSave.disabled = false;
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

    // Remember scroll position before updating so we can preserve intent.
    const el = dom.trainLogs;
    const wasAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;

    dom.trainLogs.textContent = tail || '(no log output yet)';
    dom.trainLogsWrap.classList.remove('hidden');

    // Auto-scroll to bottom only when user hasn't scrolled up to read history.
    if (wasAtBottom) {
      el.scrollTop = el.scrollHeight;
    }

    // Show progress in the summary line if we can determine iter count.
    // MLX lora prints "Training for N iters" at start and "Iter N: ..." per step.
    const totalMatch = body.match(/Training for (\d+) iter/i) || body.match(/Total iterations[:\s]+(\d+)/i);
    const iterMatches = [...body.matchAll(/Iter (\d+):/g)];
    const lastIter = iterMatches.length ? parseInt(iterMatches[iterMatches.length - 1][1], 10) : null;
    const totalIters = totalMatch ? parseInt(totalMatch[1], 10) : null;
    let progressText = '';
    if (lastIter !== null && totalIters !== null && totalIters > 0) {
      const pct = Math.min(100, Math.round((lastIter / totalIters) * 100));
      progressText = ` · Iter ${lastIter}/${totalIters} (${pct}%)`;
    } else if (lastIter !== null) {
      progressText = ` · Iter ${lastIter}`;
    }
    const summary = dom.trainLogsWrap.querySelector('summary');
    if (summary) summary.textContent = `Show training log${progressText}`;
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
        await refreshFtModels();
        // The newly trained model also needs to appear in the Manage
        // Fine-Tuned Models list so the user can delete it.  Without this
        // refresh, the list only updates on full page reload.
        await refreshFtManageList();
        break;
      }
    } catch (error) {
      setTrainStatus(`Polling error: ${error.message}`);
      break;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  state.training.polling = false;
  if (dom.trainStart) dom.trainStart.disabled = false;
}

// ---- Q/A generation (Step 2) ------------------------------------------------

function setGenerateQaStatus(msg) {
  if (dom.generateQaStatus) dom.generateQaStatus.textContent = msg || 'Idle.';
}

function renderQAPairs() {
  if (!dom.qaPairsList) return;
  const pairs = state.qa.pairs;
  if (dom.qaPairCount) {
    dom.qaPairCount.textContent = `${pairs.length} pair${pairs.length === 1 ? '' : 's'}`;
  }
  if (!pairs.length) {
    dom.qaPairsList.innerHTML = '<p class="text-sm text-muted-fg">No Q/A pairs yet. Generate them in Step 2 or add pairs manually above.</p>';
    return;
  }
  dom.qaPairsList.innerHTML = pairs
    .map(
      (pair, idx) => `
      <div class="qa-card rounded-lg border border-border bg-muted/20 p-3 space-y-2" data-row-id="${pair.row_id}">
        <div class="flex items-center gap-2">
          <button type="button" class="qa-toggle-btn flex-1 text-left flex items-center gap-2 min-w-0" data-row-id="${pair.row_id}">
            <span class="text-xs text-muted-fg shrink-0">#${idx + 1}</span>
            <span class="font-medium text-sm truncate qa-preview">${escapeHtml(pair.question.slice(0, 80))}${pair.question.length > 80 ? '…' : ''}</span>
            <span class="text-xs text-muted-fg shrink-0 qa-toggle-icon">▼</span>
          </button>
          <button type="button" class="qa-delete-btn rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10 shrink-0" data-row-id="${pair.row_id}">Delete</button>
        </div>
        <div class="qa-card-body hidden space-y-2" data-row-id="${pair.row_id}">
          <label class="block text-xs text-muted-fg">Question</label>
          <input type="text" class="qa-question-input w-full rounded-md border border-border bg-card px-3 py-2 text-sm" data-row-id="${pair.row_id}" />
          <label class="block text-xs text-muted-fg">Answer</label>
          <textarea class="qa-answer-textarea w-full rounded-md border border-border bg-card px-3 py-2 text-sm font-mono resize-y" rows="3" data-row-id="${pair.row_id}"></textarea>
          <div class="flex justify-end">
            <button type="button" class="qa-save-btn rounded-md bg-accent text-accent-fg px-3 py-1 text-xs font-medium hover:opacity-90" data-row-id="${pair.row_id}">Save changes</button>
          </div>
        </div>
      </div>`,
    )
    .join('');

  // Populate inputs/textareas via DOM to avoid quote-escaping issues
  pairs.forEach((pair) => {
    const card = dom.qaPairsList.querySelector(`.qa-card[data-row-id="${pair.row_id}"]`);
    if (!card) return;
    const qInput = card.querySelector('.qa-question-input');
    const aTextarea = card.querySelector('.qa-answer-textarea');
    if (qInput) qInput.value = pair.question;
    if (aTextarea) aTextarea.value = pair.answer;
  });

  dom.qaPairsList.querySelectorAll('.qa-toggle-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const rowId = btn.getAttribute('data-row-id');
      const body = dom.qaPairsList.querySelector(`.qa-card-body[data-row-id="${rowId}"]`);
      const icon = btn.querySelector('.qa-toggle-icon');
      if (!body) return;
      const opening = body.classList.contains('hidden');
      body.classList.toggle('hidden', !opening);
      if (icon) icon.textContent = opening ? '▲' : '▼';
    });
  });

  dom.qaPairsList.querySelectorAll('.qa-save-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const rowId = parseInt(btn.getAttribute('data-row-id'), 10);
      const card = dom.qaPairsList.querySelector(`.qa-card[data-row-id="${rowId}"]`);
      if (!card) return;
      const qInput = card.querySelector('.qa-question-input');
      const aTextarea = card.querySelector('.qa-answer-textarea');
      if (!qInput || !aTextarea) return;
      btn.disabled = true;
      try {
        await fetchJson(
          `/ft-dataset-versions/${encodeURIComponent(state.qa.versionId)}/qa-pairs/${rowId}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: qInput.value, answer: aTextarea.value }),
          },
        );
        const pair = state.qa.pairs.find((p) => p.row_id === rowId);
        if (pair) {
          pair.question = qInput.value;
          pair.answer = aTextarea.value;
          const preview = card.querySelector('.qa-preview');
          if (preview) {
            const q = pair.question;
            preview.textContent = q.slice(0, 80) + (q.length > 80 ? '…' : '');
          }
        }
      } catch (error) {
        window.alert(`Failed to save: ${error.message}`);
      } finally {
        btn.disabled = false;
      }
    });
  });

  dom.qaPairsList.querySelectorAll('.qa-delete-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const rowId = parseInt(btn.getAttribute('data-row-id'), 10);
      if (!window.confirm('Delete this Q/A pair?')) return;
      btn.disabled = true;
      try {
        await fetch(
          `/ft-dataset-versions/${encodeURIComponent(state.qa.versionId)}/qa-pairs/${rowId}`,
          { method: 'DELETE' },
        );
        state.qa.pairs = state.qa.pairs.filter((p) => p.row_id !== rowId);
        renderQAPairs();
      } catch (error) {
        window.alert(`Failed to delete: ${error.message}`);
        btn.disabled = false;
      }
    });
  });
}

if (dom.generateQaBtn) {
  dom.generateQaBtn.addEventListener('click', async () => {
    const collection = selectedCollection();
    if (!collection) {
      setGenerateQaStatus('Pick a collection in Step 1 first.');
      return;
    }
    if (!collection.document_count) {
      setGenerateQaStatus(`Collection "${collection.name}" has no documents. Upload at least one.`);
      return;
    }
    const pairs = Math.max(1, Math.min(10, Number(dom.trainPairs.value) || 3));
    const maxChunks = Math.max(1, Math.min(200, Number(dom.trainMaxChunks.value) || 20));
    let qaModelId = (dom.trainQaModel && dom.trainQaModel.value.trim()) || '';
    // Fallback: if QA model dropdown is empty, use the base model or any available model
    if (!qaModelId && state.models.length > 0) {
      qaModelId = state.models[0].modelKey || state.models[0].path || '';
    }
    dom.generateQaBtn.disabled = true;
    setGenerateQaStatus('Generating Q/A pairs from collection…');
    try {
      await ensureModelLoaded(qaModelId);
      // Build dataset name: BaseModel_Collection_YYYY-MM-DD_HH-MM
      const now = new Date();
      const today = now.toISOString().slice(0, 10);
      const time = now.toTimeString().slice(0, 5).replace(':', '-');
      const baseShort = qaModelId.split('/').pop().replace(/[^a-zA-Z0-9._-]/g, '');
      const collSafe = collection.name.replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 30);
      const datasetName = `${baseShort}_${collSafe}_${today}_${time}`;
      const built = await fetchJson('/ft-datasets/from-rag-collection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rag_collection_id: collection.id,
          dataset_name: datasetName,
          max_chunks: maxChunks,
          pairs_per_chunk: pairs,
          chat_model: qaModelId,
        }),
        timeoutMs: 600_000,  // 10 min — Qwen 4B needs ~3-5 min on M2
      });
      state.qa.versionId = built.dataset_version_id;
      setGenerateQaStatus(`Generated ${built.row_count} Q/A pairs. Fetching for review…`);
      const qaPairs = await fetchJson(
        `/ft-dataset-versions/${encodeURIComponent(state.qa.versionId)}/qa-pairs`,
      );
      state.qa.pairs = qaPairs;
      setGenerateQaStatus(
        `Generated ${state.qa.pairs.length} Q/A pairs. Review them in Step 3 below.`,
      );
      renderQAPairs();
    } catch (error) {
      // Try to extract a readable message from server JSON errors
      let msg = error.message || 'Unknown error';
      try {
        const parsed = JSON.parse(msg);
        if (parsed && parsed.message) msg = parsed.message;
        if (parsed && parsed.errors && parsed.errors.length) {
          msg += ' (' + parsed.errors[0].reason + ')';
        }
      } catch {}
      setGenerateQaStatus(msg);
    } finally {
      dom.generateQaBtn.disabled = false;
    }
  });
}

// ---- manual Q/A pair creation (Step 3) ----------------------------------------

if (dom.addPairBtn) {
  dom.addPairBtn.addEventListener('click', async () => {
    dom.addPairBtn.disabled = true;
    try {
      // If no version exists yet, create a dataset + version first
      if (!state.qa.versionId) {
        const dataset = await fetchJson('/ft-datasets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: 'Manual training data',
            task_type: 'instruction_sft',
            schema_type: 'json',
          }),
        });
        const version = await fetchJson(`/ft-datasets/${encodeURIComponent(dataset.id)}/versions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version_label: 'v1' }),
        });
        state.qa.versionId = version.id;
      }
      // Add an empty pair row to the current version
      const pair = await fetchJson(
        `/ft-dataset-versions/${encodeURIComponent(state.qa.versionId)}/qa-pairs`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: '', answer: '' }),
        },
      );
      state.qa.pairs.push(pair);
      renderQAPairs();
      // Auto-open the new card for editing
      const newCard = dom.qaPairsList.querySelector(`.qa-card[data-row-id="${pair.row_id}"]`);
      if (newCard) {
        const body = newCard.querySelector('.qa-card-body');
        const icon = newCard.querySelector('.qa-toggle-icon');
        if (body) body.classList.remove('hidden');
        if (icon) icon.textContent = '▲';
        const qInput = newCard.querySelector('.qa-question-input');
        if (qInput) { qInput.focus(); }
        newCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    } catch (error) {
      window.alert(`Failed to add pair: ${error.message}`);
    } finally {
      dom.addPairBtn.disabled = false;
    }
  });
}

// ---- fine-tune (Step 4) -----------------------------------------------------

dom.trainStart.addEventListener('click', async () => {
  if (!state.qa.versionId) {
    setTrainStatus('Generate Q/A pairs in Step 2 first.');
    return;
  }
  const selectedExposedId = dom.trainBase.value.trim() || state.selectedModelId;
  const selectedModel = state.models.find((m) => m.id === selectedExposedId);
  const base =
    (selectedModel && selectedModel.serving_model_name) ||
    selectedExposedId ||
    'liquid/lfm2.5-1.2b';
  dom.trainStart.disabled = true;
  setTrainStep('preparing_data');
  setTrainStatus('Locking dataset version…');
  try {
    const versionId = state.qa.versionId;
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
    state.training.datasetVersionId = versionId;
    setTrainStatus(`Training job ${job.id} queued. Polling…`);
    pollTrainingJob();
  } catch (error) {
    setTrainStatus(error.message);
    dom.trainStart.disabled = false;
  }
});

// ---- models -----------------------------------------------------------------

async function refreshModels() {
  // Pull all LM Studio LLMs (loaded + idle) so reviewers can pick + auto
  // load any local model. Fall back to `/v1/models` (selectable only) if
  // the LM Studio surface isn't available. Fine-tuned models that no longer
  // exist in the platform registry are filtered out so a deleted model does
  // not remain selectable from a stale LM Studio index entry.
  let llms = [];
  let registeredFtKeys = new Set();
  try {
    const allModels = await fetchJson('/models');
    registeredFtKeys = new Set(
      (allModels || [])
        .filter((m) => m.source_type === 'fine_tuned')
        .flatMap((m) => [m.serving_model_name, m.published_model_name, m.display_name, m.id])
        .filter(Boolean)
        .map((v) => String(v).toLowerCase()),
    );
  } catch {
    registeredFtKeys = new Set();
  }
  try {
    const reply = await fetchJson('/lmstudio/models');
    llms = ((reply && reply.models) || []).filter((m) => m.type === 'llm');
    llms = llms.filter((m) => {
      const keys = [m.modelKey, m.indexedModelIdentifier, m.path, m.displayName]
        .filter(Boolean)
        .map((v) => String(v).toLowerCase());
      const looksLikeFt = keys.some((k) => /_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}/.test(k));
      return !looksLikeFt || keys.some((k) => registeredFtKeys.has(k) || registeredFtKeys.has(k.split('/').pop()));
    });
  } catch {
    try {
      const fallback = await fetchJson('/v1/models');
      llms = ((fallback && fallback.data) || []).map((m) => ({
        modelKey: m.serving_model_name || m.id,
        loaded: true,
        displayName: m.id,
      }));
    } catch {
      llms = [];
    }
  }
  state.models = llms;
  if (!llms.length) {
    dom.chatModel.innerHTML = '<option value="">— no LM Studio models —</option>';
    if (dom.trainBase)
      dom.trainBase.innerHTML = '<option value="">— no LM Studio models —</option>';
    if (dom.trainQaModel)
      dom.trainQaModel.innerHTML = '<option value="">— no LM Studio models —</option>';
    state.selectedModelId = null;
    return;
  }
  // Identify FT-like models (so we can keep them out of trainBase/trainQaModel,
  // which are not meaningful targets for re-fine-tuning).
  const isFt = (m) => {
    const keys = [m.modelKey, m.indexedModelIdentifier, m.path, m.displayName]
      .filter(Boolean)
      .map((v) => String(v).toLowerCase());
    if (keys.some((k) => registeredFtKeys.has(k) || registeredFtKeys.has(k.split('/').pop()))) {
      return true;
    }
    return keys.some((k) => /_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}/.test(k));
  };
  const baseOnlyLlms = llms.filter((m) => !isFt(m));

  const renderOptions = (entries) =>
    entries
      .map((m) => {
        const id = m.modelKey || m.indexedModelIdentifier || m.path;
        const badge = m.loaded ? '[loaded]' : '[idle]';
        const label = `${id} ${badge}`;
        return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
      })
      .join('');
  const allOptionsHtml = renderOptions(llms);
  const baseOptionsHtml = renderOptions(baseOnlyLlms) || '<option value="">— no base models —</option>';

  dom.chatModel.innerHTML = allOptionsHtml;
  if (dom.trainBase) dom.trainBase.innerHTML = baseOptionsHtml;
  if (dom.trainQaModel) dom.trainQaModel.innerHTML = baseOptionsHtml;
  if (dom.verifyJudgeModel) dom.verifyJudgeModel.innerHTML = allOptionsHtml;
  const firstLoaded = llms.find((m) => m.loaded) || llms[0];
  if (!state.selectedModelId || !llms.some((m) => (m.modelKey || m.path) === state.selectedModelId)) {
    state.selectedModelId = firstLoaded.modelKey || firstLoaded.path;
  }
  dom.chatModel.value = state.selectedModelId;
  // Q/A generator: prefer exact qwen3.5-4b-mlx, then qwen3-4b/qwen3.5-4b
  // variants, then any 4B+ model. Restricted to baseOnlyLlms so a deleted-
  // looking FT model never sneaks in as the QA generator default.
  if (dom.trainQaModel && baseOnlyLlms.length) {
    const firstBaseLoaded = baseOnlyLlms.find((m) => m.loaded) || baseOnlyLlms[0];
    const qaPreferred =
      baseOnlyLlms.find((m) => (m.modelKey || '').toLowerCase() === 'qwen3.5-4b-mlx') ||
      baseOnlyLlms.find((m) => {
        const key = (m.modelKey || '').toLowerCase();
        return key.includes('qwen3.5-4b') || key.includes('qwen3-4b');
      }) ||
      baseOnlyLlms.find((m) => {
        const key = (m.modelKey || '').toLowerCase();
        return /[4-9]b|1[0-9]b|[2-9][0-9]b/.test(key);
      }) ||
      firstBaseLoaded;
    dom.trainQaModel.value = qaPreferred.modelKey || qaPreferred.path || '';
  }
  // Base model to fine-tune: prefer exact liquid/lfm2.5-1.2b, then any lfm.
  // Restricted to baseOnlyLlms so an FT model whose key contains "lfm2.5"
  // (e.g. a published "lfm2.5-1.2b_<dataset>_<timestamp>") is never the default.
  if (dom.trainBase && baseOnlyLlms.length) {
    const firstBaseLoaded = baseOnlyLlms.find((m) => m.loaded) || baseOnlyLlms[0];
    const basePreferred =
      baseOnlyLlms.find((m) => (m.modelKey || '').toLowerCase() === 'liquid/lfm2.5-1.2b') ||
      baseOnlyLlms.find((m) => {
        const key = (m.modelKey || '').toLowerCase();
        return key.includes('lfm2.5') || key.includes('lfm2');
      }) ||
      firstBaseLoaded;
    dom.trainBase.value = basePreferred.modelKey || basePreferred.path || '';
  }
  renderChatSuggestions();
}

async function ensureModelLoaded(modelId) {
  const entry = state.models.find((m) => (m.modelKey || m.path) === modelId);
  if (!entry) return true; // not in list; let generation handle availability
  if (entry.loaded) return true;
  // Model listed as idle — attempt to load but proceed regardless of outcome
  try {
    await fetchJson('/lmstudio/models/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId, identifier: modelId }),
    });
    await refreshModels();
  } catch {
    // Load failed or model already active — generation will proceed anyway
  }
  return true;
}

dom.chatModel.addEventListener('change', async (event) => {
  const value = event.target.value || null;
  state.selectedModelId = value;
  if (value) {
    await ensureModelLoaded(value);
  }
});

if (dom.trainBase) {
  dom.trainBase.addEventListener('change', async (event) => {
    const value = event.target.value || null;
    if (value) {
      await ensureModelLoaded(value);
    }
  });
}

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

// ---- Step 5: verify (LLM-as-Judge) ------------------------------------------

async function refreshFtModels() {
  if (!dom.verifyFtModel) return;
  try {
    const allModels = await fetchJson('/models');
    // Show every FT model whose files have been placed in LM Studio.
    //
    // Two publish_status values qualify:
    //   * 'published'    — publish ran and LM Studio confirmed the model is
    //                      loaded right now.
    //   * 'publish_ready'— publish ran and placed the files on disk, but the
    //                      lms-load step or the post-load probe failed (most
    //                      commonly because LM Studio TTL-unloaded the model
    //                      between publish and the next page load).  The
    //                      files still exist; the verify pipeline calls
    //                      _lmstudio_ensure_loaded per step, which will hot-
    //                      load them on demand.
    //
    // We deliberately exclude the post-train / pre-publish sentinel form
    // (`serving_model_name` starts with "artifact::") so we don't list a
    // model whose files haven't been symlinked into ~/.lmstudio/models yet.
    state.ftModels = (allModels || []).filter((m) => {
      if (m.source_type !== 'fine_tuned') return false;
      const serving = m.serving_model_name || '';
      if (!serving || serving.startsWith('artifact::')) return false;
      return m.publish_status === 'published' || m.publish_status === 'publish_ready';
    });
  } catch {
    state.ftModels = [];
  }
  if (!state.ftModels.length) {
    dom.verifyFtModel.innerHTML = '<option value="">— no published fine-tuned models —</option>';
    return;
  }
  dom.verifyFtModel.innerHTML = state.ftModels
    .map((m) => {
      const label = m.display_name || m.serving_model_name || m.id;
      // [loaded] = LM Studio has the model in memory right now.
      // [idle]   = files are on disk; first verify step will load it
      //            (a few seconds of extra latency on the first inference).
      const loaded = m.readiness && m.readiness.selectable === true;
      const badge = loaded ? '[loaded]' : '[idle]';
      const val = m.serving_model_name || m.id;
      return `<option value="${escapeHtml(val)}">${escapeHtml(label)} ${badge}</option>`;
    })
    .join('');
  updateVerifyBaseModel();
}

function updateVerifyBaseModel() {
  if (!dom.verifyFtModel || !dom.verifyBaseModel) return;
  const selectedVal = dom.verifyFtModel.value;
  const ftModel = state.ftModels.find((m) => (m.serving_model_name || m.id) === selectedVal);
  const baseModelName = (ftModel && ftModel.base_model_name) || '';
  dom.verifyBaseModel.textContent = baseModelName || '— select a fine-tuned model above —';
  loadVerifySuggestions(ftModel);
}

// Pull a representative question out of a training row, supporting both the
// instruction-SFT shape ({instruction, input}) and the chat shape (a list of
// role/content messages). Returns '' when no usable question is present.
function extractQuestionFromRow(row) {
  const inp = row && row.input_json;
  if (!inp) return '';
  if (Array.isArray(inp)) {
    const lastUser = [...inp].reverse().find((m) => m && m.role === 'user' && m.content);
    return lastUser ? String(lastUser.content).trim() : '';
  }
  if (typeof inp === 'object') {
    const instruction = String(inp.instruction || '').trim();
    const extra = String(inp.input || '').trim();
    return [instruction, extra].filter(Boolean).join('\n').trim();
  }
  return String(inp).trim();
}

// Load the fine-tune's own training questions so the user can test on
// in-domain prompts. On out-of-domain questions FT and base answer
// identically, which reads as "fine-tuning did nothing".
async function loadVerifySuggestions(ftModel) {
  state.verifySuggestions = [];
  if (dom.verifySuggestHint) dom.verifySuggestHint.textContent = '';
  if (dom.verifySuggestBtn) dom.verifySuggestBtn.disabled = true;

  const versionId = ftModel && ftModel.lineage_json && ftModel.lineage_json.dataset_version_id;
  if (!versionId) return;

  try {
    const rows = await fetchJson(`/ft-dataset-versions/${encodeURIComponent(versionId)}/rows`);
    const questions = (rows || [])
      .filter((r) => r.split === 'train')
      .map(extractQuestionFromRow)
      .filter(Boolean);
    // De-dupe while preserving order.
    state.verifySuggestions = [...new Set(questions)];
  } catch {
    state.verifySuggestions = [];
  }

  if (!state.verifySuggestions.length) return;
  if (dom.verifySuggestBtn) dom.verifySuggestBtn.disabled = false;
  if (dom.verifySuggestHint) {
    dom.verifySuggestHint.textContent = `${state.verifySuggestions.length} training question(s) available.`;
  }
  // If the user hasn't typed anything yet, pre-fill an in-domain question so
  // the default comparison is meaningful instead of a random off-topic prompt.
  if (dom.verifyQuestion && !dom.verifyQuestion.value.trim()) {
    fillSuggestedQuestion(0);
  }
}

function fillSuggestedQuestion(index) {
  const list = state.verifySuggestions || [];
  if (!list.length || !dom.verifyQuestion) return;
  const i = ((index % list.length) + list.length) % list.length;
  dom.verifyQuestion.value = list[i];
  state.verifySuggestIndex = i;
  if (dom.verifySuggestHint) {
    dom.verifySuggestHint.textContent =
      `Suggested from training data (${i + 1}/${list.length}) — edit it or click again to cycle.`;
  }
}

if (dom.verifyFtModel) {
  dom.verifyFtModel.addEventListener('change', updateVerifyBaseModel);
}

if (dom.verifySuggestBtn) {
  dom.verifySuggestBtn.addEventListener('click', () => {
    const next = (state.verifySuggestIndex === undefined ? -1 : state.verifySuggestIndex) + 1;
    fillSuggestedQuestion(next);
  });
}

function setVerifyStatus(msg) {
  if (dom.verifyStatus) dom.verifyStatus.textContent = msg || 'Idle.';
}

const VERIFY_VARIANT_LABELS = {
  ft_rag: 'FT + RAG',
  ft_only: 'FT only',
  base_rag: 'Base + RAG',
  base_only: 'Base only',
};

function renderVerifyResults(data) {
  if (!dom.verifyResultsBody || !dom.verifyResults) return;
  const variants = ['ft_rag', 'ft_only', 'base_rag', 'base_only'];
  dom.verifyResultsBody.innerHTML = variants
    .map((key) => {
      const rawScore = data.scores ? data.scores[key] : undefined;
      const comment = (data.comments && data.comments[key]) || '';
      const answer = (data.answers && data.answers[key]) || '';
      // score: null/undefined ⇒ "not graded" (judge timeout / unavailable).
      // Render "—" with neutral colour so it visually differs from a 0.
      const hasScore = rawScore !== null && rawScore !== undefined;
      const score = hasScore ? rawScore : '—';
      let scoreColor = 'text-muted-fg';
      if (hasScore) {
        scoreColor = score >= 8 ? 'text-green-400' : score >= 5 ? 'text-yellow-400' : 'text-red-400';
      }
      const scoreDisplay = hasScore ? `${escapeHtml(String(score))}/10` : '—';
      return `<tr class="align-top">
        <td class="px-3 py-2 border border-border font-medium whitespace-nowrap">${escapeHtml(VERIFY_VARIANT_LABELS[key] || key)}</td>
        <td class="px-3 py-2 border border-border max-w-xs whitespace-pre-wrap text-xs leading-relaxed">${escapeHtml(answer)}</td>
        <td class="px-3 py-2 border border-border text-center font-bold ${scoreColor}">${scoreDisplay}</td>
        <td class="px-3 py-2 border border-border text-xs text-muted-fg">${escapeHtml(comment)}</td>
      </tr>`;
    })
    .join('');

  // Three independent banners: ft_health_warning (FT model collapsed),
  // ft_similarity_warning (FT ≈ base for this question), judge_warning
  // (judge model timed out / failed). All can fire independently.
  const banner = document.getElementById('verify-ft-banner');
  if (banner) {
    const ftWarning = data.ft_health_warning;
    const judgeWarning = data.judge_warning;
    const simWarning = data.ft_similarity_warning;
    const sim = data.ft_similarity_to_base || {};
    const blocks = [];
    if (ftWarning) {
      const resolved = (data.resolved_model_ids && data.resolved_model_ids.fine_tuned) || '(unknown)';
      blocks.push(`
        <div class="rounded-md border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-200 space-y-1">
          <div class="font-semibold">⚠ Fine-tuned model failed verification</div>
          <div>${escapeHtml(ftWarning)}</div>
          <div class="text-red-300/70 font-mono break-all">FT inferenced as: ${escapeHtml(resolved)}</div>
        </div>`);
    }
    if (simWarning) {
      const resolved = (data.resolved_model_ids && data.resolved_model_ids.fine_tuned) || '(unknown)';
      const noRag = sim.no_rag !== undefined ? `${Math.round(sim.no_rag * 100)}%` : '—';
      const withRag = sim.with_rag !== undefined ? `${Math.round(sim.with_rag * 100)}%` : '—';
      blocks.push(`
        <div class="rounded-md border border-yellow-800 bg-yellow-950/40 px-3 py-2 text-xs text-yellow-200 space-y-1">
          <div class="font-semibold">ℹ Fine-tune did not differentiate from base on this question</div>
          <div>${escapeHtml(simWarning)}</div>
          <div class="text-yellow-300/70 font-mono break-all">
            FT inferenced as: ${escapeHtml(resolved)} · Jaccard similarity: no-RAG=${noRag}, with-RAG=${withRag}
          </div>
        </div>`);
    }
    if (judgeWarning) {
      blocks.push(`
        <div class="rounded-md border border-yellow-800 bg-yellow-950/40 px-3 py-2 text-xs text-yellow-200 space-y-1">
          <div class="font-semibold">⚠ Judge model could not grade</div>
          <div>${escapeHtml(judgeWarning)}</div>
        </div>`);
    }
    if (blocks.length) {
      banner.innerHTML = `<div class="space-y-2">${blocks.join('')}</div>`;
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
      banner.innerHTML = '';
    }
  }
  dom.verifyResults.classList.remove('hidden');
}

function appendVerifyLog(text) {
  if (!dom.verifyLog) return;
  const line = document.createElement('div');
  line.className = 'truncate';
  line.textContent = text;
  dom.verifyLog.appendChild(line);
}

if (dom.verifyRunBtn) {
  dom.verifyRunBtn.addEventListener('click', async () => {
    const judgeModel = dom.verifyJudgeModel && dom.verifyJudgeModel.value.trim();
    const ftModel = dom.verifyFtModel && dom.verifyFtModel.value.trim();
    const question = dom.verifyQuestion && dom.verifyQuestion.value.trim();
    const baseModel = dom.verifyBaseModel && dom.verifyBaseModel.textContent.trim();

    if (!judgeModel) { setVerifyStatus('Select a verifier model first.'); return; }
    if (!ftModel) { setVerifyStatus('Select a fine-tuned model first.'); return; }
    if (!baseModel || baseModel.startsWith('—')) { setVerifyStatus('No base model detected for the selected fine-tuned model.'); return; }
    if (!question) { setVerifyStatus('Enter a test question first.'); return; }

    const collection = selectedCollection();
    dom.verifyRunBtn.disabled = true;
    setVerifyStatus('Starting verification…');
    if (dom.verifyResults) dom.verifyResults.classList.add('hidden');
    if (dom.verifyProgress) { dom.verifyProgress.value = 0; dom.verifyProgress.classList.remove('hidden'); }
    if (dom.verifyLog) dom.verifyLog.textContent = '';
    if (dom.verifyLogWrap) { dom.verifyLogWrap.open = false; dom.verifyLogWrap.classList.remove('hidden'); }

    let seenLogCount = 0;

    try {
      // POST starts the job immediately and returns job_id — no streaming needed.
      const jobResp = await fetchJson('/inference/verify-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verifier_model: judgeModel,
          fine_tuned_model: ftModel,
          question,
          base_model: baseModel,
          rag_collection_id: collection ? collection.id : null,
        }),
      });
      const jobId = jobResp.job_id;
      setVerifyStatus('Verification started — polling for progress…');
      if (dom.verifyLogWrap) dom.verifyLogWrap.open = true;
      appendVerifyLog(`Job ${jobId} started.`);

      // Poll every 2 s until done or failed.
      // Verify-job state lives in the server's in-memory _verify_jobs dict, so
      // a restart mid-run makes the job id 404 forever. Treat 404 as terminal,
      // and cap consecutive transient errors so a real outage can't lock the
      // UI either — both paths fall through to the outer finally that re-enables
      // the Run button.
      const MAX_POLL_ERRORS = 5;
      let consecutiveErrors = 0;
      while (true) {
        await new Promise((r) => setTimeout(r, 2000));
        let job;
        try {
          job = await fetchJson(`/inference/verify-job/${encodeURIComponent(jobId)}`);
          consecutiveErrors = 0;
        } catch (pollErr) {
          const msg = pollErr.message || '';
          if (msg.includes('404')) {
            setVerifyStatus('Verification job is no longer available (did the server restart?). Reload the page and run it again.');
            appendVerifyLog(`Job lost: ${msg}`);
            break;
          }
          consecutiveErrors += 1;
          if (consecutiveErrors >= MAX_POLL_ERRORS) {
            setVerifyStatus(`Stopped polling after ${consecutiveErrors} consecutive errors: ${msg}`);
            appendVerifyLog(`Giving up: ${msg}`);
            break;
          }
          appendVerifyLog(`Poll error: ${msg} — retrying (${consecutiveErrors}/${MAX_POLL_ERRORS})…`);
          continue;
        }

        // Append any new log lines produced since last poll.
        const newEntries = (job.log_entries || []).slice(seenLogCount);
        for (const entry of newEntries) {
          appendVerifyLog(entry);
        }
        seenLogCount = (job.log_entries || []).length;

        // Update progress bar and status label from job state.
        if (dom.verifyProgress) dom.verifyProgress.value = job.step || 0;
        if (job.label) setVerifyStatus(job.label);

        if (job.status === 'done') {
          if (dom.verifyProgress) dom.verifyProgress.value = 5;
          const result = job.result;
          if (result && result.grading_error) {
            setVerifyStatus(`Grading failed: ${result.grading_error} — raw answers shown below.`);
          } else {
            setVerifyStatus('Verification complete.');
          }
          if (result) renderVerifyResults(result);
          break;
        } else if (job.status === 'failed') {
          const errMsg = job.error || 'unknown error';
          setVerifyStatus(`Verification failed: ${errMsg}`);
          appendVerifyLog(`Failed: ${errMsg}`);
          break;
        }
      }
    } catch (error) {
      setVerifyStatus(`Error: ${error.message}`);
      appendVerifyLog(`Error: ${error.message}`);
    } finally {
      dom.verifyRunBtn.disabled = false;
      if (dom.verifyProgress) dom.verifyProgress.classList.add('hidden');
    }
  });
}

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

// ---- Manage fine-tuned models (delete) ---------------------------------------

async function refreshFtManageList() {
  if (!dom.ftManageList) return;
  try {
    const allModels = await fetchJson('/models');
    const ftModels = (allModels || []).filter(
      (m) => m.source_type === 'fine_tuned',
    );
    if (!ftModels.length) {
      dom.ftManageList.innerHTML = '<span class="text-muted-fg">— no fine-tuned models —</span>';
      return;
    }
    dom.ftManageList.innerHTML = ftModels
      .map((m) => {
        const label = m.display_name || m.id;
        const hasServing = !!m.serving_model_name;
        const statusBadge = m.status === 'active'
          ? '<span class="text-green-400">● active</span>'
          : '<span class="text-yellow-400">● ' + escapeHtml(m.status) + '</span>';
        return `<div class="flex items-center justify-between gap-2 py-1 border-b border-border last:border-0">
          <div>
            <span class="font-medium">${escapeHtml(label)}</span>
            <span class="ml-2">${statusBadge}</span>
          </div>
          <button
            class="ft-delete-btn rounded border border-red-800 px-2 py-0.5 text-red-400 hover:bg-red-900/30 text-xs"
            data-model-id="${escapeHtml(m.id)}"
            data-model-name="${escapeHtml(label)}"
          >Delete</button>
        </div>`;
      })
      .join('');

    // Attach click handlers
    dom.ftManageList.querySelectorAll('.ft-delete-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.dataset.modelId;
        const modelName = btn.dataset.modelName;
        if (!confirm(`Permanently delete "${modelName}" from disk?\n\nThis will remove the model from LM Studio and delete all associated files. This cannot be undone.`)) {
          return;
        }
        btn.disabled = true;
        btn.textContent = 'Deleting…';
        try {
          const deletedModel = ftModels.find((m) => m.id === modelId) || {};
          const deletedKeys = [
            deletedModel.id,
            deletedModel.serving_model_name,
            deletedModel.published_model_name,
            deletedModel.display_name,
          ].filter(Boolean).map((v) => String(v).toLowerCase());
          await fetchJson(`/models/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
          if (deletedKeys.includes(String(state.selectedModelId || '').toLowerCase())) {
            state.selectedModelId = null;
          }
          [dom.chatModel, dom.trainBase, dom.trainQaModel, dom.verifyJudgeModel, dom.verifyFtModel].forEach((select) => {
            if (select && deletedKeys.includes(String(select.value || '').toLowerCase())) {
              select.value = '';
            }
          });
          await refreshFtManageList();
          await refreshFtModels();
          await refreshModels();
        } catch (error) {
          alert(`Delete failed: ${error.message}`);
          btn.disabled = false;
          btn.textContent = 'Delete';
        }
      });
    });
  } catch {
    dom.ftManageList.innerHTML = '<span class="text-red-400">Failed to load models.</span>';
  }
}

// ---- boot -------------------------------------------------------------------

async function boot() {
  renderChat();
  await refreshCollections();
  await refreshModels();
  await refreshFtModels();
  await refreshFtManageList();
  await refreshStatus();
}

boot().catch((error) => {
  console.error('boot failed', error);
  setKbHint(`Boot failed: ${error.message}`);
});

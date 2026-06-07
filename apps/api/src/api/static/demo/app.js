'use strict';

// Admin / evaluation / debug dashboard. Read-only inspection of the platform's
// runtime models and RAG collections. Chat lives in Open WebUI, not here.

async function getJSON(path) {
  const response = await fetch(path, { headers: { 'cache-control': 'no-store' } });
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`);
  }
  return response.json();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderList(id, items, emptyMessage) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = '';
  if (!items.length) {
    const li = document.createElement('li');
    li.textContent = emptyMessage;
    el.appendChild(li);
    return;
  }
  for (const text of items) {
    const li = document.createElement('li');
    li.textContent = text;
    el.appendChild(li);
  }
}

async function loadHealth() {
  try {
    const body = await getJSON('/health');
    setText('health-status', body.status || 'unknown');
  } catch (err) {
    setText('health-status', `unreachable (${err.message})`);
  }
}

async function loadModels() {
  try {
    const body = await getJSON('/v1/models');
    const ids = (body.data || []).map((m) => m.id);
    setText('model-count', String(ids.length));
    renderList('model-list', ids, 'No models served by the runtime yet.');
  } catch (err) {
    setText('model-count', 'unreachable');
    renderList('model-list', [], `Runtime unreachable (${err.message}).`);
  }
}

async function loadCollections() {
  try {
    const collections = await getJSON('/rag-collections');
    const rows = collections.map(
      (c) => `${c.name} — ${c.document_count} document(s) [${c.id}]`
    );
    renderList('collection-list', rows, 'No RAG collections yet.');
  } catch (err) {
    renderList('collection-list', [], `Could not load collections (${err.message}).`);
  }
}

async function init() {
  await Promise.all([loadHealth(), loadModels(), loadCollections()]);
}

document.addEventListener('DOMContentLoaded', init);

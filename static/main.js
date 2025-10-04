const state = {
  filters: {
    q: '',
    source: '',
    include_hidden: false,
    include_tried: true,
  },
  page: 1,
  pageSize: 100,
  data: [],
};

async function fetchSnapshot() {
  const res = await fetch('/api/snapshot');
  if (!res.ok) return;
  const payload = await res.json();
  document.querySelector('#last-poll').textContent = payload.last_poll || '—';
  document.querySelector('#total-codes').textContent = payload.totals?.visible ?? 0;
  renderTable(payload.candidates || []);
}

async function fetchCodes() {
  const params = new URLSearchParams({
    page: state.page,
    page_size: state.pageSize,
  });
  if (state.filters.q) params.set('q', state.filters.q);
  if (state.filters.source) params.set('source', state.filters.source);
  if (state.filters.include_hidden) params.set('include_hidden', 'true');
  if (!state.filters.include_tried) params.set('include_tried', 'false');
  const res = await fetch(`/api/codes?${params.toString()}`);
  if (!res.ok) return;
  const payload = await res.json();
  state.data = payload.items;
  document.querySelector('#total-codes').textContent = payload.total_visible;
  renderTable(state.data);
}

function renderTable(codes) {
  const tbody = document.querySelector('#codes-body');
  tbody.innerHTML = '';
  for (const candidate of codes) {
    const tr = document.createElement('tr');
    tr.dataset.code = candidate.code;
    tr.innerHTML = `
      <td>
        <div class="code-chip">
          <span>${candidate.code}</span>
          <button class="secondary copy" data-code="${candidate.code}">Copy</button>
        </div>
      </td>
      <td>
        <span title="${candidate.discovered_at}">${relativeTime(candidate.discovered_at)}</span>
      </td>
      <td>${candidate.source}</td>
      <td><a href="${candidate.url}" target="_blank" rel="noopener">Open ↗</a></td>
      <td>${escapeHtml(candidate.example_text || '')}</td>
      <td>
        <div class="actions">
          <button class="secondary mark-tried" data-code="${candidate.code}">${candidate.tried ? 'Tried' : 'Mark tried'}</button>
          <button class="secondary toggle-hidden" data-code="${candidate.code}">${candidate.hidden ? 'Unhide' : 'Hide'}</button>
          <button class="secondary delete" data-code="${candidate.code}">Delete</button>
        </div>
      </td>
    `;
    if (candidate.hidden) {
      tr.style.opacity = 0.4;
    }
    tbody.appendChild(tr);
  }
}

function relativeTime(isoString) {
  if (!isoString) return '—';
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  const date = new Date(isoString);
  const now = new Date();
  const diff = (date.getTime() - now.getTime()) / 1000;
  const thresholds = [
    { unit: 'day', value: 86400 },
    { unit: 'hour', value: 3600 },
    { unit: 'minute', value: 60 },
    { unit: 'second', value: 1 },
  ];
  for (const threshold of thresholds) {
    if (Math.abs(diff) >= threshold.value || threshold.unit === 'second') {
      return formatter.format(Math.round(diff / threshold.value), threshold.unit);
    }
  }
  return formatter.format(0, 'second');
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function attachListeners() {
  document.querySelector('#filter-q').addEventListener('input', (event) => {
    state.filters.q = event.target.value;
    debounceFetch();
  });
  document.querySelector('#filter-source').addEventListener('change', (event) => {
    state.filters.source = event.target.value;
    fetchCodes();
  });
  document.querySelector('#filter-hidden').addEventListener('change', (event) => {
    state.filters.include_hidden = event.target.checked;
    fetchCodes();
  });
  document.querySelector('#filter-tried').addEventListener('change', (event) => {
    state.filters.include_tried = event.target.checked;
    fetchCodes();
  });
  document.querySelector('#export-json').addEventListener('click', () => exportJSON());
  document.querySelector('#export-csv').addEventListener('click', () => exportCSV());
  document.querySelector('#codes-body').addEventListener('click', onTableClick);
}

let debounceTimer;
function debounceFetch() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(fetchCodes, 350);
}

async function onTableClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const code = target.dataset.code;
  if (target.classList.contains('copy')) {
    await navigator.clipboard.writeText(code);
    target.textContent = 'Copied!';
    setTimeout(() => (target.textContent = 'Copy'), 1200);
  } else if (target.classList.contains('mark-tried')) {
    await fetch(`/api/codes/${encodeURIComponent(code)}/tried`, { method: 'POST' });
    fetchCodes();
  } else if (target.classList.contains('toggle-hidden')) {
    await fetch(`/api/codes/${encodeURIComponent(code)}/hide`, { method: 'POST' });
    fetchCodes();
  } else if (target.classList.contains('delete')) {
    if (confirm(`Delete ${code}?`)) {
      await fetch(`/api/codes/${encodeURIComponent(code)}`, { method: 'DELETE' });
      fetchCodes();
    }
  }
}

function startEventStream() {
  const stream = new EventSource('/events');
  stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      prependCandidate(payload);
    } catch (error) {
      console.error('Failed to parse event', error);
    }
  };
}

function prependCandidate(candidate) {
  const tbody = document.querySelector('#codes-body');
  const existing = tbody.querySelector(`tr[data-code="${candidate.code}"]`);
  if (existing) {
    existing.remove();
  }
  const row = document.createElement('tr');
  row.dataset.code = candidate.code;
  row.innerHTML = `
    <td>
      <div class="code-chip">
        <span>${candidate.code}</span>
        <button class="secondary copy" data-code="${candidate.code}">Copy</button>
      </div>
    </td>
    <td><span title="${candidate.discovered_at}">${relativeTime(candidate.discovered_at)}</span></td>
    <td>${candidate.source}</td>
    <td><a href="${candidate.url}" target="_blank" rel="noopener">Open ↗</a></td>
    <td>${escapeHtml(candidate.example_text || '')}</td>
    <td>
      <div class="actions">
        <button class="secondary mark-tried" data-code="${candidate.code}">${candidate.tried ? 'Tried' : 'Mark tried'}</button>
        <button class="secondary toggle-hidden" data-code="${candidate.code}">${candidate.hidden ? 'Unhide' : 'Hide'}</button>
        <button class="secondary delete" data-code="${candidate.code}">Delete</button>
      </div>
    </td>
  `;
  tbody.prepend(row);
}

function exportJSON() {
  const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: 'application/json' });
  downloadBlob(blob, 'sora-invite-codes.json');
}

function exportCSV() {
  const header = ['code', 'source', 'source_title', 'url', 'example_text', 'discovered_at', 'tried', 'hidden'];
  const rows = [header.join(',')];
  for (const record of state.data) {
    const line = header.map((key) => `"${String(record[key] ?? '').replace(/"/g, '""')}`);
    rows.push(line.join(','));
  }
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  downloadBlob(blob, 'sora-invite-codes.csv');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function bootstrap() {
  attachListeners();
  await fetchSnapshot();
  await fetchCodes();
  startEventStream();
}

document.addEventListener('DOMContentLoaded', bootstrap);

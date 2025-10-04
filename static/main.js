const state = {
  filters: {
    q: '',
    source: '',
    showTried: false,
    showHidden: false,
  },
  page: 1,
  pageSize: 50,
  total: 0,
  loading: false,
  logsPaused: false,
  logName: 'app',
  logsTimer: null,
  items: [],
};

const elements = {
  kpiLastPoll: document.getElementById('kpi-last-poll'),
  kpiTotal: document.getElementById('kpi-total'),
  kpiLast24h: document.getElementById('kpi-last-24h'),
  kpiSources: document.getElementById('kpi-sources'),
  tableBody: document.getElementById('codes-body'),
  tableCount: document.getElementById('table-count'),
  loadMore: document.getElementById('load-more'),
  filterForm: document.getElementById('filters'),
  filterQuery: document.getElementById('filter-q'),
  filterSource: document.getElementById('filter-source'),
  filterShowTried: document.getElementById('filter-show-tried'),
  filterShowHidden: document.getElementById('filter-show-hidden'),
  filterRefresh: document.getElementById('filter-refresh'),
  filterReset: document.getElementById('filter-reset'),
  sourcesBody: document.getElementById('sources-body'),
  recheckSources: document.getElementById('recheck-sources'),
  logsView: document.getElementById('logs-view'),
  logSelect: document.getElementById('log-select'),
  logLines: document.getElementById('log-lines'),
  logsRefresh: document.getElementById('logs-refresh'),
  logsToggle: document.getElementById('logs-toggle'),
  exportJson: document.getElementById('export-json'),
  exportCsv: document.getElementById('export-csv'),
  exportJsonPage: document.getElementById('export-json-page'),
  exportCsvPage: document.getElementById('export-csv-page'),
};

function formatRelative(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffSec = Math.round(diffMs / 1000);
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  const absSec = Math.abs(diffSec);
  if (absSec < 60) return rtf.format(Math.round(diffSec), 'second');
  const diffMin = Math.round(diffSec / 60);
  if (Math.abs(diffMin) < 60) return rtf.format(diffMin, 'minute');
  const diffHour = Math.round(diffMin / 60);
  if (Math.abs(diffHour) < 24) return rtf.format(diffHour, 'hour');
  const diffDay = Math.round(diffHour / 24);
  return rtf.format(diffDay, 'day');
}

function buildQuery(params) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    searchParams.set(key, value);
  });
  return searchParams.toString();
}

function currentFilterParams(overrides = {}) {
  const params = {
    q: state.filters.q,
    source: state.filters.source,
    include_tried: state.filters.showTried ? '1' : '0',
    include_hidden: state.filters.showHidden ? '1' : '0',
  };
  return { ...params, ...overrides };
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function renderKPIs(snapshot) {
  elements.kpiLastPoll.textContent = snapshot.last_poll ? formatRelative(snapshot.last_poll) : '—';
  if (snapshot.last_poll) {
    elements.kpiLastPoll.title = new Date(snapshot.last_poll).toLocaleString();
  }
  const totals = snapshot.totals || {};
  elements.kpiTotal.textContent = totals.visible ?? 0;
  elements.kpiLast24h.textContent = totals.last_24h ?? 0;
  const sources = snapshot.active_sources || [];
  elements.kpiSources.textContent = sources.length;
  updateSourceOptions(sources);
}

function updateSourceOptions(sources) {
  const select = elements.filterSource;
  const current = select.value;
  select.innerHTML = '<option value="">All sources</option>';
  sources.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  if (sources.includes(current)) {
    select.value = current;
  }
}

function renderCandidates(items, append = false) {
  if (!append) {
    state.items = [];
    elements.tableBody.innerHTML = '';
  }
  const fragment = document.createDocumentFragment();
  items.forEach((item) => {
    state.items.push(item);
    fragment.appendChild(buildRow(item));
  });
  elements.tableBody.appendChild(fragment);
  updateTableInfo();
}

function buildRow(item) {
  const tr = document.createElement('tr');

  const codeCell = document.createElement('td');
  const codeWrapper = document.createElement('span');
  codeWrapper.className = 'code-pill';
  const codeText = document.createElement('span');
  codeText.textContent = item.code;
  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => copyToClipboard(item.code));
  codeWrapper.append(codeText, copyBtn);
  codeCell.appendChild(codeWrapper);
  tr.appendChild(codeCell);

  const discoveredCell = document.createElement('td');
  discoveredCell.textContent = formatRelative(item.discovered_at);
  if (item.discovered_at) {
    discoveredCell.title = new Date(item.discovered_at).toLocaleString();
  }
  tr.appendChild(discoveredCell);

  const sourceCell = document.createElement('td');
  sourceCell.textContent = item.source || '—';
  tr.appendChild(sourceCell);

  const linkCell = document.createElement('td');
  if (item.url) {
    const link = document.createElement('a');
    link.href = item.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open';
    linkCell.appendChild(link);
  } else {
    linkCell.textContent = '—';
  }
  tr.appendChild(linkCell);

  const snippetCell = document.createElement('td');
  snippetCell.textContent = item.example_text || '—';
  tr.appendChild(snippetCell);

  const actionsCell = document.createElement('td');
  actionsCell.appendChild(actionButton('Tried', () => markTried(item.code)));
  actionsCell.appendChild(actionButton(item.hidden ? 'Unhide' : 'Hide', () => toggleHidden(item.code)));
  actionsCell.appendChild(actionButton('Delete', () => deleteCode(item.code), 'danger'));
  tr.appendChild(actionsCell);

  return tr;
}

function actionButton(label, handler, variant) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = variant === 'danger' ? 'secondary danger' : 'secondary';
  btn.textContent = label;
  btn.addEventListener('click', handler);
  return btn;
}

function updateTableInfo() {
  elements.tableCount.textContent = `${state.total} results`;
  elements.loadMore.style.display = state.items.length < state.total ? 'inline-flex' : 'none';
}

async function loadCodes({ reset = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (reset) {
    state.page = 1;
  }
  const params = currentFilterParams({ page: state.page, page_size: state.pageSize });
  try {
    const data = await fetchJSON(`/api/codes?${buildQuery(params)}`);
    state.total = data.total;
    const items = data.items || [];
    renderCandidates(items, !reset && state.page > 1);
    if (reset) {
      elements.tableBody.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (error) {
    console.error('Failed to load codes', error);
  } finally {
    state.loading = false;
  }
}

async function applyFilters() {
  state.filters.q = elements.filterQuery.value.trim();
  state.filters.source = elements.filterSource.value;
  state.filters.showTried = elements.filterShowTried.checked;
  state.filters.showHidden = elements.filterShowHidden.checked;
  await loadCodes({ reset: true });
}

function setupFilters() {
  elements.filterForm.addEventListener('submit', (event) => {
    event.preventDefault();
  });
  [elements.filterQuery, elements.filterSource].forEach((input) => {
    input.addEventListener('change', () => applyFilters());
  });
  elements.filterShowHidden.addEventListener('change', () => applyFilters());
  elements.filterShowTried.addEventListener('change', () => applyFilters());
  elements.filterRefresh.addEventListener('click', () => applyFilters());
  elements.filterReset.addEventListener('click', () => {
    elements.filterQuery.value = '';
    elements.filterSource.value = '';
    elements.filterShowHidden.checked = false;
    elements.filterShowTried.checked = false;
    applyFilters();
  });
  elements.loadMore.addEventListener('click', () => {
    state.page += 1;
    loadCodes({ reset: false });
  });
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    console.warn('Clipboard copy failed', error);
  }
}

async function markTried(code) {
  await fetchJSON(`/api/codes/${encodeURIComponent(code)}/tried`, { method: 'POST' });
  await loadCodes({ reset: true });
}

async function toggleHidden(code) {
  await fetchJSON(`/api/codes/${encodeURIComponent(code)}/hide`, { method: 'POST' });
  await loadCodes({ reset: true });
}

async function deleteCode(code) {
  if (!confirm(`Delete ${code}?`)) return;
  await fetchJSON(`/api/codes/${encodeURIComponent(code)}`, { method: 'DELETE' });
  await loadCodes({ reset: true });
}

function setupNavigation() {
  const navButtons = document.querySelectorAll('.nav-link');
  navButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      navButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.dataset.target;
      document.querySelectorAll('.view').forEach((view) => {
        view.classList.toggle('active', view.id === `view-${target}`);
      });
    });
  });
}

async function refreshSnapshot() {
  try {
    const snapshot = await fetchJSON('/api/snapshot');
    renderKPIs(snapshot);
    renderSources(snapshot.sources_health || []);
  } catch (error) {
    console.error('Failed to load snapshot', error);
  }
}

function renderSources(sources) {
  elements.sourcesBody.innerHTML = '';
  const fragment = document.createDocumentFragment();
  sources.forEach((item) => {
    const tr = document.createElement('tr');
    const urlCell = document.createElement('td');
    const link = document.createElement('a');
    link.href = item.url;
    link.textContent = item.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    urlCell.appendChild(link);
    tr.appendChild(urlCell);

    const statusCell = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'badge ' + (item.ok ? 'ok' : item.status_code ? 'warn' : 'error');
    if (item.ok) {
      badge.textContent = `OK (${item.status_code})`;
    } else if (item.status_code) {
      badge.textContent = `HTTP ${item.status_code}`;
    } else {
      badge.textContent = 'Error';
    }
    statusCell.appendChild(badge);
    tr.appendChild(statusCell);

    const lastCheckedCell = document.createElement('td');
    lastCheckedCell.textContent = item.last_checked_iso ? formatRelative(item.last_checked_iso) : '—';
    if (item.last_checked_iso) {
      lastCheckedCell.title = new Date(item.last_checked_iso).toLocaleString();
    }
    tr.appendChild(lastCheckedCell);

    const errorCell = document.createElement('td');
    errorCell.textContent = item.error || '—';
    tr.appendChild(errorCell);

    fragment.appendChild(tr);
  });
  elements.sourcesBody.appendChild(fragment);
}

async function recheckSources() {
  try {
    elements.recheckSources.disabled = true;
    const data = await fetchJSON('/api/sources/recheck', { method: 'POST' });
    renderSources(data.sources || []);
  } catch (error) {
    console.error('Failed to recheck sources', error);
  } finally {
    elements.recheckSources.disabled = false;
  }
}

async function loadLogs() {
  if (state.logsPaused) return;
  try {
    const name = state.logName;
    const lines = Math.max(50, Math.min(1000, parseInt(elements.logLines.value, 10) || 200));
    const data = await fetchJSON(`/api/logs/tail?${buildQuery({ name, lines })}`);
    const text = (data.lines || []).join('\n');
    elements.logsView.textContent = text || 'No log entries.';
    elements.logsView.scrollTop = elements.logsView.scrollHeight;
  } catch (error) {
    elements.logsView.textContent = 'Unable to load logs.';
  }
}

function setupLogs() {
  elements.logSelect.addEventListener('change', () => {
    state.logName = elements.logSelect.value;
    loadLogs();
  });
  elements.logsRefresh.addEventListener('click', () => {
    loadLogs();
  });
  elements.logsToggle.addEventListener('click', () => {
    state.logsPaused = !state.logsPaused;
    elements.logsToggle.textContent = state.logsPaused ? 'Resume' : 'Pause';
    if (!state.logsPaused) {
      loadLogs();
    }
  });
  if (state.logsTimer) clearInterval(state.logsTimer);
  state.logsTimer = setInterval(() => loadLogs(), 8000);
}

function buildExportUrl(format) {
  const params = currentFilterParams();
  const endpoint = format === 'json' ? '/api/export.json' : '/api/export.csv';
  const query = buildQuery({ ...params, limit: 5000 });
  return `${endpoint}?${query}`;
}

function setupExports() {
  const openExport = (format) => {
    window.open(buildExportUrl(format), '_blank');
  };
  elements.exportJson.addEventListener('click', () => openExport('json'));
  elements.exportCsv.addEventListener('click', () => openExport('csv'));
  elements.exportJsonPage.addEventListener('click', () => openExport('json'));
  elements.exportCsvPage.addEventListener('click', () => openExport('csv'));
}

function setupEventStream() {
  const source = new EventSource('/events');
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (shouldDisplay(data)) {
        loadCodes({ reset: true });
      }
      refreshSnapshot();
    } catch (error) {
      console.error('Failed to parse SSE payload', error);
    }
  };
  source.onerror = () => {
    source.close();
    setTimeout(setupEventStream, 5000);
  };
}

function shouldDisplay(candidate) {
  if (!candidate) return false;
  if (state.filters.source && candidate.source !== state.filters.source) return false;
  if (!state.filters.showHidden && candidate.hidden) return false;
  if (!state.filters.showTried && candidate.tried) return false;
  if (state.filters.q) {
    const haystack = `${candidate.code} ${candidate.source_title || ''} ${candidate.example_text || ''}`.toUpperCase();
    if (!haystack.includes(state.filters.q.toUpperCase())) {
      return false;
    }
  }
  return true;
}

async function bootstrap() {
  setupNavigation();
  setupFilters();
  setupLogs();
  setupExports();
  elements.recheckSources.addEventListener('click', () => recheckSources());
  await Promise.all([refreshSnapshot(), loadCodes({ reset: true }), loadLogs()]);
  setupEventStream();
  setInterval(() => refreshSnapshot(), 60000);
}

bootstrap().catch((error) => console.error(error));

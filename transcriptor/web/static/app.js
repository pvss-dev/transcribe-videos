'use strict';

const $ = (id) => document.getElementById(id);

const dropzone = $('dropzone');
const fileInput = $('file-input');
const errorEl = $('error');
const jobsEl = $('jobs');
const emptyEl = $('empty');
const clearBtn = $('clear-btn');
const template = $('job-template');
const themeToggle = $('theme-toggle');

// job id -> { el, source }
const jobs = new Map();

const STATUS_LABELS = {
  queued: 'Na fila',
  uploading: 'Enviando',
  loading_model: 'Carregando modelo',
  transcribing: 'Transcrevendo',
  completed: 'Concluída',
  error: 'Erro',
  cancelling: 'Cancelando',
  cancelled: 'Cancelada',
};

const TERMINAL = new Set(['completed', 'error', 'cancelled']);

/* ---------- theme ---------- */

function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.setAttribute(
    'aria-label',
    theme === 'light' ? 'Mudar para tema escuro' : 'Mudar para tema claro',
  );
  try {
    localStorage.setItem('theme', theme);
  } catch (e) { /* private mode; applies for this visit only */ }
}

themeToggle.addEventListener('click', () => {
  applyTheme(currentTheme() === 'light' ? 'dark' : 'light');
});
applyTheme(currentTheme());

/* ---------- formatting ---------- */

function formatBytes(bytes) {
  if (!bytes) return '0 MB';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatClock(seconds) {
  if (seconds === null || seconds === undefined) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
}

async function explainFailure(response, fallback) {
  // The app answers with JSON; nginx's own rate-limit page is HTML, so
  // parsing has to be allowed to fail.
  const detail = await response.json().then((d) => d.detail).catch(() => null);
  if (detail) return detail;
  if (response.status === 429) {
    return 'Muitas requisições em pouco tempo. Espere um minuto e tente de novo.';
  }
  if (response.status === 413) return 'Arquivo grande demais.';
  return fallback;
}

/* ---------- job cards ---------- */

function renderJob(job) {
  let entry = jobs.get(job.id);

  if (!entry) {
    const el = template.content.firstElementChild.cloneNode(true);
    el.dataset.id = job.id;
    el.querySelector('.btn-cancel').addEventListener('click', () => cancelJob(job.id));
    jobsEl.prepend(el);
    entry = { el, source: null };
    jobs.set(job.id, entry);
  }

  const { el } = entry;
  el.dataset.status = job.status;
  el.querySelector('.job-title').textContent = job.source_name;
  el.querySelector('.job-status').textContent = STATUS_LABELS[job.status] || job.status;
  el.querySelector('.progress-bar').style.width = `${job.percent}%`;

  const stats = [];
  if (job.status === 'uploading') {
    stats.push(`${job.percent.toFixed(0)}%`);
    if (job.total_bytes) {
      stats.push(`${formatBytes(job.uploaded_bytes)} / ${formatBytes(job.total_bytes)}`);
    }
  } else if (job.status === 'transcribing') {
    stats.push(`${job.percent.toFixed(1)}%`);
    const done = formatClock(job.seconds_done);
    const total = formatClock(job.seconds_total);
    if (done && total) stats.push(`${done} de ${total}`);
  } else if (job.status === 'loading_model') {
    stats.push(`modelo ${job.model}`);
  } else if (job.status === 'completed') {
    if (job.detected_language) stats.push(`idioma: ${job.detected_language}`);
  }
  el.querySelector('.job-stats').textContent = stats.join('  ·  ');

  const transcript = el.querySelector('.btn-transcript');
  transcript.hidden = !job.transcript_path;
  if (job.transcript_path) transcript.href = `/api/jobs/${job.id}/transcript`;

  const srt = el.querySelector('.btn-srt');
  srt.hidden = !job.has_srt;
  if (job.has_srt) srt.href = `/api/jobs/${job.id}/subtitles`;

  const preview = el.querySelector('.job-transcript');
  if (job.transcript_preview) {
    preview.textContent = job.transcript_preview;
    preview.hidden = false;
  } else {
    preview.hidden = true;
  }

  const err = el.querySelector('.job-error');
  if (job.error && job.status !== 'cancelled') {
    err.textContent = job.error;
    err.hidden = false;
  } else {
    err.hidden = true;
  }

  refreshChrome();
}

function refreshChrome() {
  emptyEl.hidden = jobs.size > 0;
  clearBtn.hidden = ![...jobs.values()].some((e) => TERMINAL.has(e.el.dataset.status));
}

function dropPlaceholder(id) {
  const entry = jobs.get(id);
  if (!entry) return;
  entry.el.remove();
  jobs.delete(id);
  refreshChrome();
}

/* ---------- SSE ---------- */

function subscribe(jobId) {
  const entry = jobs.get(jobId);
  if (!entry || entry.source) return;

  const source = new EventSource(`/api/jobs/${jobId}/events`);
  entry.source = source;

  source.onmessage = (event) => renderJob(JSON.parse(event.data));

  source.addEventListener('done', (event) => {
    renderJob(JSON.parse(event.data));
    source.close();
    entry.source = null;
  });

  source.onerror = () => {
    // The stream ends normally when the job finishes; only give up if the
    // job is already in a terminal state.
    if (!TERMINAL.has(entry.el.dataset.status)) return;
    source.close();
    entry.source = null;
  };
}

async function cancelJob(jobId) {
  await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' }).catch(() => {});
}

/* ---------- upload ---------- */

function uploadFile(file) {
  if (!file) return;
  errorEl.hidden = true;

  const body = new FormData();
  body.append('file', file);
  body.append('whisper_model', $('whisper_model').value);
  body.append('language', $('language').value);

  // A placeholder card carries the browser-side upload progress, which
  // fetch() cannot report; XMLHttpRequest still can.
  const placeholderId = `upload-${Date.now()}`;
  const placeholder = (loaded, total) => ({
    id: placeholderId,
    status: 'uploading',
    percent: total ? (loaded / total) * 100 : 0,
    source_name: file.name,
    uploaded_bytes: loaded,
    total_bytes: total,
  });
  renderJob(placeholder(0, file.size));

  const request = new XMLHttpRequest();
  request.open('POST', '/api/transcribe');

  request.upload.addEventListener('progress', (event) => {
    if (event.lengthComputable) renderJob(placeholder(event.loaded, event.total));
  });

  request.addEventListener('load', () => {
    dropPlaceholder(placeholderId);
    if (request.status >= 400) {
      let detail = null;
      try {
        detail = JSON.parse(request.responseText).detail;
      } catch (e) { /* nginx errors are HTML, not JSON */ }
      showError(detail || (request.status === 429
        ? 'Muitas requisições em pouco tempo. Espere um minuto e tente de novo.'
        : request.status === 413
        ? 'Arquivo grande demais.'
        : 'Falha ao enviar o arquivo.'));
      return;
    }
    const job = JSON.parse(request.responseText);
    renderJob(job);
    subscribe(job.id);
  });

  request.addEventListener('error', () => {
    dropPlaceholder(placeholderId);
    showError('Falha ao contatar o servidor.');
  });

  request.send(body);
}

dropzone.addEventListener('click', (event) => {
  if (event.target !== $('browse-btn')) fileInput.click();
});
$('browse-btn').addEventListener('click', (event) => {
  event.stopPropagation();
  fileInput.click();
});
fileInput.addEventListener('change', () => {
  uploadFile(fileInput.files[0]);
  fileInput.value = '';
});

// Dropping anywhere on the page works; the zone is only the visible target.
let dragDepth = 0;

window.addEventListener('dragenter', (event) => {
  if (!event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  dragDepth += 1;
  dropzone.classList.add('dragging');
});

window.addEventListener('dragover', (event) => {
  if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
});

window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropzone.classList.remove('dragging');
});

window.addEventListener('drop', (event) => {
  if (!event.dataTransfer?.files.length) return;
  event.preventDefault();
  dragDepth = 0;
  dropzone.classList.remove('dragging');
  uploadFile(event.dataTransfer.files[0]);
});

clearBtn.addEventListener('click', async () => {
  await fetch('/api/jobs', { method: 'DELETE' }).catch(() => {});
  for (const [id, entry] of jobs) {
    if (TERMINAL.has(entry.el.dataset.status)) {
      entry.source?.close();
      entry.el.remove();
      jobs.delete(id);
    }
  }
  refreshChrome();
});

/* ---------- boot ---------- */

async function boot() {
  try {
    const health = await (await fetch('/api/health')).json();
    $('version').textContent = health.transcription_available ? 'Whisper pronto' : 'indisponível';
    $('dropzone-sub').textContent = `áudio ou vídeo, até ${health.max_upload_mb} MB`;

    if (!health.transcription_available) {
      dropzone.classList.add('disabled');
      $('browse-btn').disabled = true;
      showError('O Whisper não está instalado neste servidor.');
    }
  } catch (e) {
    $('version').textContent = 'servidor offline';
  }

  // Restore jobs still tracked by the server after a page reload.
  try {
    const { jobs: existing } = await (await fetch('/api/jobs')).json();
    for (const job of existing.slice().reverse()) {
      renderJob(job);
      if (!TERMINAL.has(job.status)) subscribe(job.id);
    }
  } catch (e) { /* nothing to restore */ }

  refreshChrome();
}

boot();

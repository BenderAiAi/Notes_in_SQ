const state = {
  settings: { source_dir: "", output_dir: "" },
  scan: null,
  selected: null,
  dictionary: [],
};

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try { payload = await response.json(); } catch (_error) { /* empty response */ }
  if (!response.ok) {
    const error = new Error(payload.error || `Ошибка запроса (${response.status})`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function toast(message, type = "success") {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.textContent = message;
  $("#toast-region").append(element);
  window.setTimeout(() => element.remove(), 4300);
}

function setLoading(button, active) {
  button.classList.toggle("loading", active);
  button.disabled = active;
}

function formatDate(iso) {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}.${month}.${year}`;
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return `${formatDate(iso)} ${iso.slice(11, 16)}`;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "0";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 12 }).format(number);
}

function plural(value, one, few, many) {
  const n = Math.abs(Number(value)) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}

function openModal(id) { $(`#${id}`).classList.remove("hidden"); }
function closeModal(id) { $(`#${id}`).classList.add("hidden"); }

async function loadSettings() {
  state.settings = await api("/api/settings");
  $("#source-dir").value = state.settings.source_dir;
  $("#output-dir").value = state.settings.output_dir;
}

async function browseFolder(button) {
  const input = $(`#${button.dataset.target}`);
  setLoading(button, true);
  try {
    const result = await api("/api/browse-folder", jsonOptions("POST", { initial: input.value }));
    if (result.path) input.value = result.path;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function scanReports(force = false) {
  const button = $("#scan-button");
  const sourceDir = $("#source-dir").value.trim();
  const outputDir = $("#output-dir").value.trim();
  if (!sourceDir || !outputDir) {
    toast("Укажите обе рабочие папки.", "error");
    return;
  }
  setLoading(button, true);
  try {
    const result = await api("/api/reports/scan", jsonOptions("POST", {
      source_dir: sourceDir,
      output_dir: outputDir,
      force,
    }));
    state.scan = result;
    state.settings = result.settings;
    if (!result.files.length) {
      $("#report-result").classList.add("hidden");
      $("#empty-state").classList.remove("hidden");
      toast(result.stats.found ? "Excel-файлы найдены, но ни один не распознан как отчёт." : "В папке нет подходящих Excel-файлов.", "error");
      return;
    }
    $("#empty-state").classList.add("hidden");
    $("#report-result").classList.remove("hidden");
    $("#choose-file-button").classList.toggle("hidden", result.files.length < 2);
    await selectReport(result.candidates[0] || result.files[0]);
    if (result.candidates.length > 1) showFileChooser(result.candidates);
    const indexText = result.stats.from_index
      ? `Проверено: ${result.stats.found}. Из индекса: ${result.stats.from_index}.`
      : `Проверено файлов: ${result.stats.found}.`;
    toast(indexText);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function selectReport(candidate) {
  if (!candidate) return;
  try {
    const analysis = await api("/api/reports/analyze", jsonOptions("POST", { path: candidate.path }));
    state.selected = analysis;
    renderReport(analysis);
    closeModal("file-modal");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderReport(report) {
  $("#selected-file-name").textContent = report.file_name;
  $("#selected-date").textContent = formatDate(report.latest_trade_date);
  $("#selected-modified").textContent = formatDateTime(report.modified_at);
  $("#selected-rows").textContent = formatNumber(report.summary.rows);
  $("#buy-amount").textContent = formatNumber(report.summary.buy_amount);
  $("#buy-trades").textContent = `${report.summary.buy_trades} ${plural(report.summary.buy_trades, "сделка", "сделки", "сделок")}`;
  $("#sell-amount").textContent = formatNumber(report.summary.sell_amount);
  $("#sell-trades").textContent = `${report.summary.sell_trades} ${plural(report.summary.sell_trades, "сделка", "сделки", "сделок")}`;
  $("#unique-isin").textContent = formatNumber(report.summary.unique_isin);

  const date = report.latest_trade_date?.replaceAll("-", "");
  const formattedNameDate = date ? `${date.slice(6, 8)}${date.slice(4, 6)}${date.slice(0, 4)}` : "DDMMYYYY";
  $("#output-name").textContent = `Note_trades_sq_${formattedNameDate}.xlsx`;

  const alert = $("#date-alert");
  const today = state.scan?.today;
  if (today && report.latest_trade_date !== today) {
    alert.className = "alert warning";
    alert.innerHTML = `<strong>Отчёт за сегодня не найден.</strong>&nbsp; Выбран последний доступный файл за ${formatDate(report.latest_trade_date)}. Перед формированием проверьте дату.`;
  } else {
    alert.className = "alert success";
    alert.innerHTML = `<strong>Дата актуальна.</strong>&nbsp; В файле есть сделки за сегодня — ${formatDate(report.latest_trade_date)}.`;
  }
  renderSourcePreview(report);
  renderIssues(report);
}

function renderSourcePreview(report) {
  const headers = report.source_headers || [];
  const rows = report.preview_rows || [];
  const head = $("#source-preview-head");
  const body = $("#source-preview-rows");
  head.innerHTML = "";
  body.innerHTML = "";

  const headerRow = document.createElement("tr");
  const rowNumberHeader = document.createElement("th");
  rowNumberHeader.textContent = "Строка";
  headerRow.append(rowNumberHeader);
  headers.forEach(header => {
    const cell = document.createElement("th");
    cell.textContent = header;
    headerRow.append(cell);
  });
  head.append(headerRow);

  rows.forEach(row => {
    const tableRow = document.createElement("tr");
    const rowNumber = document.createElement("td");
    rowNumber.className = "source-row-number";
    rowNumber.textContent = row.source_row ?? "";
    tableRow.append(rowNumber);
    (row.cells || []).forEach(value => {
      const cell = document.createElement("td");
      cell.textContent = value ?? "";
      cell.title = value ?? "";
      tableRow.append(cell);
    });
    body.append(tableRow);
  });

  const count = rows.length;
  $("#source-preview-summary").textContent = `${count} ${plural(count, "строка сделки", "строки сделки", "строк сделок")} · ${headers.length} столбцов`;
}

function renderIssues(report) {
  const container = $("#issues-list");
  const status = $("#diagnostic-status");
  const generate = $("#generate-button");
  const hint = $("#generate-hint");
  container.innerHTML = "";
  const issues = [...report.errors, ...report.warnings, ...(report.notices || [])];
  if (!issues.length) {
    const item = document.createElement("div");
    item.className = "issue ok";
    item.textContent = "Проверки пройдены: структура, сделки, даты и справочник заполнены корректно.";
    container.append(item);
    status.className = "status-pill ok";
    status.textContent = "Готово";
  } else {
    issues.forEach(issue => {
      const item = document.createElement("div");
      item.className = `issue ${issue.level}`;
      item.textContent = issue.message;
      container.append(item);
    });
    if (report.errors.length) {
      status.className = "status-pill error";
      status.textContent = `${report.errors.length} ${plural(report.errors.length, "ошибка", "ошибки", "ошибок")}`;
    } else if (report.warnings.length) {
      status.className = "status-pill warning";
      status.textContent = `${report.warnings.length} ${plural(report.warnings.length, "предупреждение", "предупреждения", "предупреждений")}`;
    } else {
      status.className = "status-pill ok";
      status.textContent = "Готово";
    }
  }
  generate.disabled = !report.can_generate;
  hint.textContent = report.can_generate
    ? (report.warnings.length ? "Будет запрошено подтверждение" : "Все обязательные проверки пройдены")
    : "Исправьте ошибки, выделенные выше";
}

function showFileChooser(files = state.scan?.files || []) {
  const container = $("#file-options");
  container.innerHTML = "";
  files.forEach(file => {
    const button = document.createElement("button");
    button.className = "file-option";
    button.type = "button";
    button.innerHTML = `<div><strong>${escapeHtml(file.file_name)}</strong><small>${file.summary.rows} строк · ${file.summary.unique_isin} ISIN</small></div><span>${formatDate(file.latest_trade_date)}</span><span>${formatDateTime(file.modified_at)}</span>`;
    button.addEventListener("click", () => selectReport(file));
    container.append(button);
  });
  openModal("file-modal");
}

async function generateReport(overwrite = false) {
  if (!state.selected?.can_generate) return;
  if (state.selected.warnings.length && !overwrite) {
    const proceed = window.confirm("В отчёте есть предупреждения. Всё равно сформировать файл?");
    if (!proceed) return;
  }
  const button = $("#generate-button");
  setLoading(button, true);
  try {
    const result = await api("/api/reports/generate", jsonOptions("POST", { path: state.selected.path, overwrite }));
    toast(`Файл сформирован: ${result.file_name}`);
    $("#generate-hint").textContent = `Сохранён: ${result.path}`;
  } catch (error) {
    if (error.payload?.requires_overwrite) {
      const proceed = window.confirm(`Файл уже существует:\n${error.payload.path}\n\nЗаменить его?`);
      if (proceed) await generateReport(true);
    } else if (error.payload?.analysis) {
      state.selected = error.payload.analysis;
      renderReport(state.selected);
      toast(error.message, "error");
    } else {
      toast(error.message, "error");
    }
  } finally {
    setLoading(button, false);
  }
}

async function loadDictionary(search = "") {
  try {
    const result = await api(`/api/dictionary?search=${encodeURIComponent(search)}`);
    state.dictionary = result.items;
    renderDictionary();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderDictionary() {
  const body = $("#dictionary-body");
  body.innerHTML = "";
  state.dictionary.forEach(entry => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><strong>${escapeHtml(entry.isin)}</strong></td>
      <td>${displayValue(entry.note)}</td>
      <td>${displayValue(entry.note_name_sq)}</td>
      <td>${displayValue(entry.portfolio)}</td>
      <td>${displayValue(entry.subportfolio)}</td>
      <td>${displayValue(entry.subaccount)}</td>
      <td><div class="row-actions"><button class="mini-button edit-entry" title="Изменить">✎</button><button class="mini-button danger delete-entry" title="Удалить">×</button></div></td>`;
    $(".edit-entry", row).addEventListener("click", () => openEntryForm(entry));
    $(".delete-entry", row).addEventListener("click", () => deleteEntry(entry));
    body.append(row);
  });
  const count = state.dictionary.length;
  $("#dictionary-count").textContent = `${count} ${plural(count, "запись", "записи", "записей")}`;
  $("#dictionary-empty").classList.toggle("hidden", count !== 0);
}

function displayValue(value) {
  return value ? escapeHtml(value) : '<span class="missing-value">не заполнено</span>';
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

function openEntryForm(entry = null) {
  const form = $("#entry-form");
  form.reset();
  $("#entry-id").value = entry?.id || "";
  $("#entry-modal-title").textContent = entry ? "Изменить ноту" : "Новая нота";
  ["note", "isin", "note_name_sq", "portfolio", "subportfolio", "subaccount"].forEach(field => {
    form.elements[field].value = entry?.[field] || "";
  });
  openModal("entry-modal");
  window.setTimeout(() => form.elements.isin.focus(), 50);
}

async function saveEntry(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("button[type='submit']", form);
  const id = $("#entry-id").value;
  const payload = Object.fromEntries(new FormData(form).entries());
  setLoading(button, true);
  try {
    await api(id ? `/api/dictionary/${id}` : "/api/dictionary", jsonOptions(id ? "PUT" : "POST", payload));
    closeModal("entry-modal");
    await loadDictionary($("#dictionary-search").value);
    toast(id ? "Запись обновлена." : "Нота добавлена в справочник.");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function deleteEntry(entry) {
  if (!window.confirm(`Удалить ${entry.isin} из справочника?`)) return;
  try {
    await api(`/api/dictionary/${entry.id}`, { method: "DELETE" });
    await loadDictionary($("#dictionary-search").value);
    toast("Запись удалена.");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function importDictionary(file) {
  if (!file) return;
  const button = $("#dictionary-import-button");
  const form = new FormData();
  form.append("file", file);
  setLoading(button, true);
  try {
    const result = await api("/api/dictionary/import", { method: "POST", body: form });
    await loadDictionary();
    toast(`Импорт завершён: добавлено ${result.created}, обновлено ${result.updated}.`);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
    $("#dictionary-import-input").value = "";
  }
}

function bindEvents() {
  $$(".tab").forEach(tab => tab.addEventListener("click", () => {
    $$(".tab").forEach(item => item.classList.toggle("active", item === tab));
    $$(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === `${tab.dataset.tab}-tab`));
  }));
  $("#settings-toggle").addEventListener("click", event => {
    const expanded = event.currentTarget.getAttribute("aria-expanded") === "true";
    event.currentTarget.setAttribute("aria-expanded", String(!expanded));
    $("#settings-body").classList.toggle("collapsed", expanded);
  });
  $("#source-preview-toggle").addEventListener("click", event => {
    const expanded = event.currentTarget.getAttribute("aria-expanded") === "true";
    event.currentTarget.setAttribute("aria-expanded", String(!expanded));
    $("#source-preview-body").classList.toggle("collapsed", expanded);
  });
  $$(".browse-button").forEach(button => button.addEventListener("click", () => browseFolder(button)));
  $("#scan-button").addEventListener("click", () => scanReports(false));
  $("#choose-file-button").addEventListener("click", () => showFileChooser());
  $("#generate-button").addEventListener("click", () => generateReport(false));
  $("#add-entry-button").addEventListener("click", () => openEntryForm());
  $("#entry-form").addEventListener("submit", saveEntry);
  $$('[data-close-modal]').forEach(element => element.addEventListener("click", () => closeModal(element.dataset.closeModal)));
  let searchTimer;
  $("#dictionary-search").addEventListener("input", event => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadDictionary(event.target.value), 220);
  });
  $("#dictionary-import-button").addEventListener("click", () => $("#dictionary-import-input").click());
  $("#dictionary-import-input").addEventListener("change", event => importDictionary(event.target.files[0]));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") $$(".modal:not(.hidden)").forEach(modal => closeModal(modal.id));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  try {
    await Promise.all([loadSettings(), loadDictionary()]);
  } catch (error) {
    toast(`Не удалось инициализировать приложение: ${error.message}`, "error");
  }
});

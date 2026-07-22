(() => {
const state = {
  settings: { source_dir: "", output_dir: "" },
  scan: null,
  selected: null,
};

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try { payload = await response.json(); } catch (_error) { /* пусто */ }
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
  window.setTimeout(() => element.remove(), 4600);
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
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(number);
}

function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(number)} %`;
}

function plural(value, one, few, many) {
  const n = Math.abs(Number(value)) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}

function todayName() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[c]));
}

function termModalId(id) { return id.startsWith("term-") ? id : `term-${id}`; }
function openModal(id) { $(`#${termModalId(id)}`).classList.remove("hidden"); }
function closeModal(id) { $(`#${termModalId(id)}`).classList.add("hidden"); }

const TYPE_LABELS = { dubai: "Dubai", trs: "TRS", both: "Dubai+TRS", not_found: "не найден" };

async function loadSettings() {
  state.settings = await api("/terminations/api/settings");
  $("#term-source-dir").value = state.settings.source_dir;
  $("#term-output-dir").value = state.settings.output_dir;
}

async function browseFolder(button) {
  const input = $(`#${button.dataset.target}`);
  setLoading(button, true);
  try {
    const result = await api("/terminations/api/browse-folder", jsonOptions("POST", { initial: input.value }));
    if (result.path) input.value = result.path;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function scanReports(force = false) {
  const button = $("#term-scan-button");
  const sourceDir = $("#term-source-dir").value.trim();
  const outputDir = $("#term-output-dir").value.trim();
  if (!sourceDir || !outputDir) {
    toast("Укажите обе рабочие папки.", "error");
    return;
  }
  setLoading(button, true);
  try {
    const result = await api("/terminations/api/reports/scan", jsonOptions("POST", { source_dir: sourceDir, output_dir: outputDir, force }));
    state.scan = result;
    state.settings = result.settings;
    if (!result.files.length) {
      $("#term-report-result").classList.add("hidden");
      $("#term-empty-state").classList.remove("hidden");
      toast(result.stats.found ? "Excel-файлы найдены, но ни один не распознан как файл расторжений." : "В папке нет подходящих Excel-файлов.", "error");
      return;
    }
    $("#term-empty-state").classList.add("hidden");
    $("#term-report-result").classList.remove("hidden");
    $("#term-choose-file-button").classList.toggle("hidden", result.files.length < 2);
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
    const analysis = await api("/terminations/api/reports/analyze", jsonOptions("POST", { path: candidate.path }));
    state.selected = analysis;
    renderReport(analysis);
    closeModal("file-modal");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderReport(report) {
  const summary = report.summary;
  $("#term-selected-file-name").textContent = report.file_name;
  $("#term-selected-date").textContent = formatDate(report.latest_termination_date);
  $("#term-selected-modified").textContent = formatDateTime(report.modified_at);
  $("#term-selected-rows").textContent = summary.total;
  $("#term-selected-found").textContent = `${summary.found} из ${summary.total}`;

  const rate = summary.rate;
  $("#term-rate-avg").textContent = formatPercent(rate.avg);
  $("#term-rate-range").textContent = rate.min === null ? "нет данных" : `от ${formatPercent(rate.min)} до ${formatPercent(rate.max)}`;
  renderTypeMetric("dubai", summary.dubai);
  renderTypeMetric("trs", summary.trs);
  $("#term-cyprus-count").textContent = summary.cyprus_count;
  $("#term-cyprus-card").classList.toggle("on", summary.cyprus_count > 0);

  const notFoundPill = $("#term-not-found-pill");
  if (summary.not_found.length) {
    notFoundPill.className = "status-pill error";
    notFoundPill.textContent = `${summary.not_found.length} не найдено в Mongo`;
  } else {
    notFoundPill.className = "status-pill ok";
    notFoundPill.textContent = "Все найдены в Mongo";
  }

  renderContracts(report.contracts);
  renderOutputs(summary);
  renderDateAlert(report);
  renderIssues(report);
}

function renderTypeMetric(kind, data) {
  const total = $(`#term-${kind}-total`);
  const split = $(`#term-${kind}-split`);
  if (!data) {
    total.textContent = "нет";
    split.textContent = "расторжений нет";
    return;
  }
  total.textContent = `${data.total} ${plural(data.total, "расторжение", "расторжения", "расторжений")}`;
  const parts = [`${data.manual} ручных`, `${data.mssp} МССП`];
  if (data.unknown) parts.push(`${data.unknown} без статуса`);
  split.textContent = parts.join(" · ");
}

function renderContracts(contracts) {
  const body = $("#term-contracts-body");
  body.innerHTML = "";
  contracts.forEach((contract) => {
    const row = document.createElement("tr");
    if (contract.cyprus) row.className = "is-cyprus";
    else if (!contract.found) row.className = "not-found";
    const mismatch = contract.notional_mismatch ? " mismatch" : "";
    const rateClass = contract.rate_alert ? " rate-alert" : "";
    row.innerHTML = `
      <td><strong>${escapeHtml(contract.contract_number)}</strong></td>
      <td><span class="badge ${contract.type}">${TYPE_LABELS[contract.type] || contract.type}</span></td>
      <td><span class="badge ${contract.dissolution_type}">${escapeHtml(contract.dissolution_label)}</span></td>
      <td>${formatDate(contract.termination_date)}</td>
      <td class="num${rateClass}">${formatPercent(contract.rate_pct)}</td>
      <td class="num${mismatch}">${formatNumber(contract.notional_file)}</td>
      <td class="num${mismatch}">${formatNumber(contract.notional_mongo)}</td>
      <td class="num">${formatNumber(contract.termination_amount)}</td>
      <td>${escapeHtml(contract.currency)}</td>
      <td>${contract.cyprus ? `<span class="badge cyprus">${escapeHtml(contract.cyprus_value || "Да")}</span>` : ""}</td>`;
    body.append(row);
  });
}

function renderOutputs(summary) {
  const name = todayName();
  $("#term-file-dubai").textContent = summary.dubai ? `${name}-Dubai_term.xlsx` : "Dubai: контрактов нет";
  $("#term-file-trs").textContent = summary.trs ? `${name}-TRS_term.xlsx` : "TRS: контрактов нет";
}

function renderDateAlert(report) {
  const alert = $("#term-date-alert");
  alert.classList.remove("hidden");
  if (report.today && report.latest_termination_date !== report.today) {
    alert.className = "alert warning";
    alert.innerHTML = `<strong>Дата расторжения ≠ сегодня.</strong>&nbsp; В файле ${formatDate(report.latest_termination_date)}. Проверьте, тот ли это файл, или выберите другой.`;
  } else {
    alert.className = "alert success";
    alert.innerHTML = `<strong>Дата актуальна.</strong>&nbsp; Расторжения на сегодня — ${formatDate(report.latest_termination_date)}.`;
  }
}

function renderIssues(report) {
  const container = $("#term-issues-list");
  const status = $("#term-diagnostic-status");
  const generate = $("#term-generate-button");
  const hint = $("#term-generate-hint");
  container.innerHTML = "";
  const issues = [...report.errors, ...report.alerts, ...report.warnings, ...report.notices];
  if (!issues.length) {
    const item = document.createElement("div");
    item.className = "issue ok";
    item.textContent = "Проверки пройдены: контракты найдены, номиналы и валюты сходятся.";
    container.append(item);
    status.className = "status-pill ok";
    status.textContent = "Готово";
  } else {
    issues.forEach((issue) => {
      const item = document.createElement("div");
      item.className = `issue ${issue.level}`;
      item.textContent = issue.message;
      container.append(item);
    });
    if (report.errors.length) {
      status.className = "status-pill error";
      status.textContent = `${report.errors.length} ${plural(report.errors.length, "ошибка", "ошибки", "ошибок")}`;
    } else if (report.alerts.length || report.warnings.length) {
      status.className = "status-pill warning";
      const count = report.alerts.length + report.warnings.length;
      status.textContent = `${count} ${plural(count, "предупреждение", "предупреждения", "предупреждений")}`;
    } else {
      status.className = "status-pill ok";
      status.textContent = "Готово";
    }
  }
  generate.disabled = !report.can_generate;
  hint.textContent = report.can_generate
    ? "Отчёты будут сохранены в папку готовых файлов"
    : "Нет контрактов, найденных в Mongo";
}

function showFileChooser(files = state.scan?.files || []) {
  const container = $("#term-file-options");
  container.innerHTML = "";
  files.forEach((file) => {
    const button = document.createElement("button");
    button.className = "file-option";
    button.type = "button";
    button.innerHTML = `<div><strong>${escapeHtml(file.file_name)}</strong><small>${file.row_count} контрактов · ${file.manual_count} ручных · ${file.mssp_count} МССП</small></div><span>${formatDate(file.latest_termination_date)}</span><span>${formatDateTime(file.modified_at)}</span>`;
    button.addEventListener("click", () => selectReport(file));
    container.append(button);
  });
  openModal("file-modal");
}

async function generateReport(overwrite = false) {
  if (!state.selected?.can_generate) return;
  const analysis = state.selected;
  if (!overwrite && (analysis.alerts.length || analysis.warnings.length)) {
    const messages = [];
    if (analysis.today && analysis.latest_termination_date !== analysis.today) {
      messages.push(`Дата в файле: ${formatDate(analysis.latest_termination_date)}. Сегодня: ${formatDate(analysis.today)}.`);
    }
    if (analysis.alerts.length) messages.push("Есть контракты со связью на Кипре.");
    if (analysis.warnings.some((issue) => issue.code === "found_in_both")) {
      messages.push("Есть контракты, найденные одновременно в Dubai и TRS — они попадут в оба отчёта.");
    }
    if (analysis.warnings.some((issue) => issue.code === "not_found")) {
      messages.push("Контракты, не найденные в Mongo, будут пропущены.");
    }
    if (!messages.length) messages.push("В отчёте есть предупреждения.");
    if (!window.confirm(`${messages.join("\n")}\n\nВсё равно сформировать отчёты с датой ${formatDate(analysis.today)}?`)) return;
  }
  const button = $("#term-generate-button");
  setLoading(button, true);
  try {
    const result = await api("/terminations/api/reports/generate", jsonOptions("POST", { path: analysis.path, overwrite }));
    const saved = result.saved;
    toast(`Готово: Dubai ${saved.dubai_count}, TRS ${saved.trs_count}. История +${result.history.created} ~${result.history.updated}.`);
    $("#term-generate-hint").textContent = `Сохранено в папку готовых отчётов`;
    loadHistory();
  } catch (error) {
    if (error.payload?.requires_overwrite) {
      if (window.confirm(`Файлы уже существуют:\n${(error.payload.files || []).join("\n")}\n\nЗаменить?`)) await generateReport(true);
    } else {
      toast(error.message, "error");
    }
  } finally {
    setLoading(button, false);
  }
}

// ---------------------------------------------------------------------------
// История
// ---------------------------------------------------------------------------

function historyFilters() {
  return {
    search: $("#term-history-search").value.trim(),
    currency: $("#term-history-currency").value,
    date_from: $("#term-history-from").value,
    date_to: $("#term-history-to").value,
  };
}

function historyQuery() {
  const filters = historyFilters();
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString();
}

async function loadHistory() {
  try {
    const query = historyQuery();
    const result = await api(`/terminations/api/history${query ? `?${query}` : ""}`);
    renderHistory(result);
    $("#term-history-export").href = `/terminations/api/history/export${query ? `?${query}` : ""}`;
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderHistory(result) {
  const body = $("#term-history-body");
  body.innerHTML = "";
  result.items.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.cyprus_flag) tr.className = "is-cyprus";
    tr.innerHTML = `
      <td>${formatDate(row.termination_date)}</td>
      <td><strong>${escapeHtml(row.contract_number)}</strong></td>
      <td><span class="badge ${row.contract_type}">${TYPE_LABELS[row.contract_type] || row.contract_type}</span></td>
      <td class="num">${formatPercent(row.rate_pct)}</td>
      <td class="num">${formatNumber(row.termination_amount)}</td>
      <td>${escapeHtml(row.return_currency)}</td>
      <td class="num">${formatNumber(row.notional)}</td>
      <td><span class="badge ${row.dissolution_type}">${row.dissolution_type === "manual" ? "Ручное" : row.dissolution_type === "mssp" ? "МССП" : "—"}</span></td>
      <td>${row.cyprus_flag ? '<span class="badge cyprus">Да</span>' : ""}</td>
      <td>${escapeHtml(row.source_file)}</td>
      <td>${formatDateTime(row.updated_at)}</td>`;
    body.append(tr);
  });
  const count = result.items.length;
  $("#term-history-count").textContent = `${count} ${plural(count, "запись", "записи", "записей")}`;
  $("#term-history-empty").classList.toggle("hidden", count !== 0);
  $("#term-history-sums").textContent = (result.summary.by_currency || [])
    .map((row) => `${row.currency}: ${formatNumber(row.termination_sum)}`).join("   ");
  updateCurrencyOptions(result.summary.by_currency || []);
}

function updateCurrencyOptions(byCurrency) {
  const select = $("#term-history-currency");
  const current = select.value;
  const currencies = byCurrency.map((row) => row.currency).filter((c) => c && c !== "—");
  select.innerHTML = '<option value="">Все валюты</option>' + currencies.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  select.value = current;
}

function bindEvents() {
  $('[data-tab="term-history"]').addEventListener("click", loadHistory);
  $("#term-settings-toggle").addEventListener("click", (event) => {
    const expanded = event.currentTarget.getAttribute("aria-expanded") === "true";
    event.currentTarget.setAttribute("aria-expanded", String(!expanded));
    $("#term-settings-body").classList.toggle("collapsed", expanded);
  });
  $("#term-diagnostics-toggle").addEventListener("click", (event) => {
    const expanded = event.currentTarget.getAttribute("aria-expanded") === "true";
    event.currentTarget.setAttribute("aria-expanded", String(!expanded));
    event.currentTarget.setAttribute("aria-label", expanded ? "Развернуть диагностику" : "Свернуть диагностику");
    $("#term-issues-list").classList.toggle("collapsed", expanded);
  });
  $$(".browse-button", $("#term-report-tab")).forEach((button) => button.addEventListener("click", () => browseFolder(button)));
  $("#term-scan-button").addEventListener("click", () => scanReports(false));
  $("#term-choose-file-button").addEventListener("click", () => showFileChooser());
  $("#term-generate-button").addEventListener("click", () => generateReport(false));
  $$('[data-close-modal]', $("#term-file-modal")).forEach((element) => element.addEventListener("click", () => closeModal(element.dataset.closeModal)));

  let searchTimer;
  $("#term-history-search").addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(loadHistory, 220);
  });
  $("#term-history-currency").addEventListener("change", loadHistory);
  $("#term-history-from").addEventListener("change", loadHistory);
  $("#term-history-to").addEventListener("change", loadHistory);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#term-file-modal").classList.contains("hidden")) closeModal("term-file-modal");
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  try {
    await loadSettings();
  } catch (error) {
    toast(`Не удалось инициализировать приложение: ${error.message}`, "error");
  }
});
})();

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------- i18n (static UI strings; mode texts come from the API) ----------

  const I18N = {
    en: {
      title: "Image processing",
      mode: "Processing mode",
      image: "Image",
      choose_file: "Choose a file",
      or_drop: "or drop it here",
      settings: "Settings",
      run: "Process",
      result: "Result",
      download_result: "Download result",
      download_original: "Download original",
      log: "Processing log",
      hide_processed: "Hide processed",
      show_processed: "Show processed",
      hold_space: "Hold Space to peek at the original",
      fit: "Fit",
      placeholder: "Upload an image, adjust the settings and press \"Process\".",
      placeholder_hint: "Mouse wheel zooms, drag pans, hold Space to peek at the original.",
      uploading: "Uploading {name}…",
      processing: "Processing… large photos can take up to a minute.",
      done: "Done",
      not_selected: "— not selected —",
      search: "Search by name…",
      original: "Original",
      processed: "Processed",
      rt_available: "available",
      rt_missing: "not found",
      health: "RawTherapee: {rt} · LCP profiles: {lcp} · modes: {modes}",
      rt_missing_warn: "RawTherapee was not found on the server. Modes that need it will not run.",
      modes_load_failed: "Could not load the mode list: {error}",
      camera: "Camera: {value}",
      lens: "Lens: {value}",
      size: "Size: {w} × {h}",
      profile_auto: "LCP profile picked automatically",
      profile_none: "No LCP profile matched the EXIF",
      not_viewable: "The browser cannot show this format: a preview appears after processing",
      image_load_failed: "Could not load the image",
      request_error: "Request failed",
      histogram: "Histogram",
      table: "Table",
      on: "on",
      off: "off",
      not_selected_short: "auto",
      kb: "KB",
      mb: "MB",
    },
    ru: {
      title: "Обработка изображений",
      mode: "Режим обработки",
      image: "Изображение",
      choose_file: "Выберите файл",
      or_drop: "или перетащите сюда",
      settings: "Настройки",
      run: "Обработать",
      result: "Результат",
      download_result: "Скачать результат",
      download_original: "Скачать оригинал",
      log: "Лог обработки",
      hide_processed: "Скрыть обработанное",
      show_processed: "Показать обработанное",
      hold_space: "Удерживайте пробел, чтобы временно показать оригинал",
      fit: "Вписать",
      placeholder: "Загрузите изображение, настройте параметры и нажмите «Обработать».",
      placeholder_hint: "Колесо мыши — зум, перетаскивание — сдвиг, пробел — показать оригинал.",
      uploading: "Загрузка {name}…",
      processing: "Обработка… большие снимки могут занять до минуты.",
      done: "Готово",
      not_selected: "— не выбрано —",
      search: "Поиск по названию…",
      original: "Оригинал",
      processed: "Обработанное",
      rt_available: "доступен",
      rt_missing: "не найден",
      health: "RawTherapee: {rt} · профилей LCP: {lcp} · режимов: {modes}",
      rt_missing_warn: "RawTherapee не найден на сервере. Режимы, которые его используют, не запустятся.",
      modes_load_failed: "Не удалось загрузить список режимов: {error}",
      camera: "Камера: {value}",
      lens: "Объектив: {value}",
      size: "Размер: {w} × {h}",
      profile_auto: "Профиль LCP подобран автоматически",
      profile_none: "Профиль LCP не подобран по EXIF",
      not_viewable: "Формат не отображается браузером: превью появится после обработки",
      image_load_failed: "Не удалось загрузить изображение",
      request_error: "Ошибка запроса",
      histogram: "Гистограмма",
      table: "Таблица",
      on: "вкл",
      off: "выкл",
      not_selected_short: "авто",
      kb: "КБ",
      mb: "МБ",
    },
  };

  const LANG_KEY = "ipp.lang";

  function loadLang() {
    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved && I18N[saved]) return saved;
    } catch (_) {}
    return "en";
  }

  function saveLang(lang) {
    try { localStorage.setItem(LANG_KEY, lang); } catch (_) {}
  }

  function t(key, vars) {
    let text = (I18N[state.lang] && I18N[state.lang][key]) || I18N.en[key] || key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) text = text.replace("{" + k + "}", v);
    }
    return text;
  }

  const els = {
    mode: $("mode"),
    modeDescription: $("mode-description"),
    file: $("file"),
    dropzone: $("dropzone"),
    uploadInfo: $("upload-info"),
    paramsBlock: $("params-block"),
    params: $("params"),
    run: $("run"),
    status: $("status"),
    resultBlock: $("result-block"),
    notes: $("notes"),
    report: $("report"),
    actions: $("actions"),
    download: $("download"),
    downloadOriginal: $("download-original"),
    log: $("log"),
    health: $("health"),
    toolbar: $("toolbar"),
    toggle: $("toggle"),
    fit: $("fit"),
    zoom100: $("zoom-100"),
    zoomLevel: $("zoom-level"),
    layerLabel: $("layer-label"),
    viewport: $("viewport"),
    stage: $("stage"),
    imgOriginal: $("img-original"),
    imgProcessed: $("img-processed"),
    placeholder: $("placeholder"),
  };

  const state = {
    lang: loadLang(),
    modes: [],
    mode: null,
    upload: null,
    result: null,
    health: null,
    busy: false,
    showProcessed: true,
    holdOriginal: false,
    view: { x: 0, y: 0, scale: 1 },
    image: { width: 0, height: 0 },
  };

  function applyStaticStrings() {
    document.documentElement.lang = state.lang;
    for (const node of document.querySelectorAll("[data-i18n]")) {
      node.textContent = t(node.dataset.i18n);
    }
    for (const node of document.querySelectorAll("[data-i18n-title]")) {
      node.title = t(node.dataset.i18nTitle);
    }
    for (const btn of document.querySelectorAll(".lang-switch .lang")) {
      btn.classList.toggle("active", btn.dataset.lang === state.lang);
    }
    updateLayers();
    renderHealth();
  }

  // ---------- helpers ----------

  function setStatus(text, kind) {
    if (!text) {
      els.status.hidden = true;
      els.status.textContent = "";
      els.status.className = "status";
      return;
    }
    els.status.hidden = false;
    els.status.textContent = text;
    els.status.className = "status" + (kind ? " " + kind : "");
  }

  async function api(url, options) {
    const sep = url.includes("?") ? "&" : "?";
    const res = await fetch(url + sep + "lang=" + state.lang, options);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const detail = data && data.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : detail || res.statusText || t("request_error");
      throw new Error(message);
    }
    return data;
  }

  function formatBytes(n) {
    if (n == null) return "";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " " + t("kb");
    return (n / (1024 * 1024)).toFixed(1) + " " + t("mb");
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function updateRunButton() {
    els.run.disabled = state.busy || !state.upload || !state.mode;
  }

  function renderHealth() {
    const h = state.health;
    if (!h) return;
    els.health.textContent = t("health", {
      rt: h.rawtherapee ? t("rt_available") : t("rt_missing"),
      lcp: h.lcp_files,
      modes: state.modes.length,
    });
  }

  // ---------- modes and params ----------

  async function loadModes() {
    const modes = await api("/api/modes");
    state.modes = modes;
    const keepMode = state.mode ? state.mode.id : null;
    const values = collectParams();
    renderModes(keepMode);
    for (const [name, value] of Object.entries(values)) {
      if (value !== null && value !== undefined) setParam(name, value);
    }
    applySuggestions();
    renderHealth();
  }

  function renderModes(preferredId) {
    els.mode.innerHTML = "";
    for (const mode of state.modes) {
      const opt = document.createElement("option");
      opt.value = mode.id;
      opt.textContent = mode.name;
      els.mode.appendChild(opt);
    }
    if (!state.modes.length) return;
    const target = state.modes.find((m) => m.id === preferredId) ? preferredId : state.modes[0].id;
    selectMode(target);
  }

  function selectMode(id) {
    state.mode = state.modes.find((m) => m.id === id) || null;
    els.mode.value = id;
    els.modeDescription.textContent = state.mode ? state.mode.description : "";
    renderParams();
    updateRunButton();
  }

  function renderParams() {
    els.params.innerHTML = "";
    if (!state.mode || !state.mode.params.length) {
      els.paramsBlock.hidden = true;
      return;
    }
    els.paramsBlock.hidden = false;
    let currentSection = null;
    for (const spec of state.mode.params) {
      const section = spec.section || "";
      if (section && section !== currentSection) {
        els.params.appendChild(el("div", "param-section", section));
      }
      currentSection = section || currentSection;
      els.params.appendChild(renderParam(spec));
    }
    applySuggestions();
  }

  function defaultText(spec) {
    if (spec.type === "bool") return t(spec.default ? "on" : "off");
    if (spec.type === "select") {
      if (spec.default == null || spec.default === "") return t("not_selected_short");
      const opt = (spec.options || []).find((o) => o.value === spec.default);
      return opt ? opt.label : String(spec.default);
    }
    if (spec.default == null || spec.default === "") return "";
    return String(spec.default);
  }

  function labelWithDefault(spec) {
    const d = defaultText(spec);
    return d ? `${spec.label} (${d})` : spec.label;
  }

  function renderParam(spec) {
    const wrap = document.createElement("div");
    wrap.className = "param " + spec.type;
    wrap.dataset.name = spec.name;

    if (spec.type === "bool") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = "param-" + spec.name;
      input.checked = !!spec.default;
      const label = document.createElement("label");
      label.htmlFor = input.id;
      label.textContent = labelWithDefault(spec);
      wrap.append(input, label);
      if (spec.help) wrap.appendChild(el("span", "hint", spec.help));
      return wrap;
    }

    const label = document.createElement("label");
    label.htmlFor = "param-" + spec.name;
    label.textContent = labelWithDefault(spec);
    wrap.appendChild(label);

    if (spec.type === "select") {
      const select = document.createElement("select");
      select.id = "param-" + spec.name;
      const many = spec.options.length > 12;
      let filter = null;
      if (many) {
        filter = document.createElement("input");
        filter.type = "text";
        filter.className = "filter";
        filter.placeholder = t("search");
        wrap.appendChild(filter);
      }
      const fill = (query) => {
        const q = (query || "").trim().toLowerCase();
        const current = select.value;
        select.innerHTML = "";
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = t("not_selected");
        select.appendChild(empty);
        const groups = new Map();
        for (const o of spec.options) {
          if (q && !o.label.toLowerCase().includes(q)) continue;
          const key = o.group || "";
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(o);
        }
        for (const [group, options] of groups) {
          const parent = group ? document.createElement("optgroup") : select;
          if (group) {
            parent.label = group;
            select.appendChild(parent);
          }
          for (const o of options) {
            const opt = document.createElement("option");
            opt.value = o.value;
            opt.textContent = o.label;
            parent.appendChild(opt);
          }
        }
        if (current && [...select.options].some((o) => o.value === current)) select.value = current;
        else if (spec.default != null) select.value = spec.default;
      };
      fill("");
      if (filter) filter.addEventListener("input", () => fill(filter.value));
      select._fill = fill;
      wrap.appendChild(select);
    } else if (spec.type === "number") {
      const input = document.createElement("input");
      input.type = "number";
      input.id = "param-" + spec.name;
      if (spec.min != null) input.min = spec.min;
      if (spec.max != null) input.max = spec.max;
      if (spec.step != null) input.step = spec.step;
      if (spec.default != null) input.value = spec.default;
      wrap.appendChild(input);
    }

    if (spec.help) wrap.appendChild(el("span", "hint", spec.help));
    return wrap;
  }

  function collectParams() {
    const params = {};
    if (!state.mode) return params;
    for (const spec of state.mode.params) {
      const input = $("param-" + spec.name);
      if (!input) continue;
      if (spec.type === "bool") params[spec.name] = input.checked;
      else if (spec.type === "number") params[spec.name] = input.value === "" ? null : Number(input.value);
      else params[spec.name] = input.value || null;
    }
    return params;
  }

  function setParam(name, value) {
    const input = $("param-" + name);
    if (!input) return false;
    if (input.tagName === "SELECT") {
      const filter = input.parentElement.querySelector(".filter");
      if (filter && filter.value) {
        filter.value = "";
        input._fill("");
      }
      input.value = value;
      return input.value === value;
    }
    if (input.type === "checkbox") input.checked = !!value;
    else input.value = value;
    return true;
  }

  function applySuggestions() {
    if (!state.upload) return;
    if (state.upload.suggested_profile) {
      setParam("profile", state.upload.suggested_profile);
    }
  }

  // ---------- language switch ----------

  async function setLang(lang) {
    if (!I18N[lang] || lang === state.lang) return;
    state.lang = lang;
    saveLang(lang);
    applyStaticStrings();
    if (state.upload) renderUploadInfo(state.upload);
    try {
      await loadModes();
    } catch (err) {
      setStatus(t("modes_load_failed", { error: err.message }), "error");
    }
    updateRunButton();
  }

  for (const btn of document.querySelectorAll(".lang-switch .lang")) {
    btn.addEventListener("click", () => setLang(btn.dataset.lang));
  }

  // ---------- upload ----------

  async function uploadFile(file) {
    if (!file) return;
    state.upload = null;
    state.result = null;
    els.resultBlock.hidden = true;
    updateRunButton();
    setStatus(t("uploading", { name: file.name }), "busy");
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/api/uploads", { method: "POST", body: form });
      state.upload = data;
      renderUploadInfo(data);
      applySuggestions();
      setStatus("");
      if (data.original_url) {
        await showImages(data.original_url, null);
      } else {
        clearViewer();
      }
    } catch (err) {
      setStatus(err.message, "error");
      els.uploadInfo.hidden = true;
    } finally {
      updateRunButton();
    }
  }

  function renderUploadInfo(data) {
    const meta = data.meta || {};
    els.uploadInfo.innerHTML = "";
    const add = (text, strong) => {
      const row = el("span");
      if (strong) {
        row.appendChild(el("b", null, strong));
        row.appendChild(document.createTextNode(text));
      } else {
        row.textContent = text;
      }
      els.uploadInfo.appendChild(row);
    };
    add(" · " + formatBytes(data.size), data.filename);
    const camera = [meta.camera_make, meta.camera_model].filter(Boolean).join(" ");
    if (camera) add(t("camera", { value: camera }));
    if (meta.lens_model) add(t("lens", { value: meta.lens_model }));
    if (meta.width && meta.height) add(t("size", { w: meta.width, h: meta.height }));
    add(data.suggested_profile ? t("profile_auto") : t("profile_none"));
    if (!data.browser_viewable) add(t("not_viewable"));
    els.uploadInfo.hidden = false;
  }

  // ---------- processing ----------

  async function run() {
    if (!state.upload || !state.mode || state.busy) return;
    state.busy = true;
    updateRunButton();
    setStatus(t("processing"), "busy");
    els.resultBlock.hidden = true;
    try {
      const data = await api(`/api/uploads/${state.upload.id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: state.mode.id, params: collectParams(), lang: state.lang }),
      });
      state.result = data;
      renderResult(data);
      setStatus(t("done"), "ok");
      await showImages(data.original_url, data.processed_url, true);
    } catch (err) {
      setStatus(err.message, "error");
    } finally {
      state.busy = false;
      updateRunButton();
    }
  }

  function renderResult(data) {
    els.resultBlock.hidden = false;
    els.notes.innerHTML = "";
    const info = data.info || {};
    for (const n of info.notes || []) els.notes.appendChild(el("li", null, n));

    renderReport(info.report);

    els.download.href = data.download_url;
    els.downloadOriginal.href = data.download_original_url;
    for (const old of els.actions.querySelectorAll(".extra-file")) old.remove();
    for (const f of data.files || []) {
      const a = el("a", "button secondary extra-file", f.label || f.name);
      a.href = f.url;
      a.setAttribute("download", "");
      els.actions.appendChild(a);
    }
    els.log.textContent = data.log || "";
  }

  // ---------- report ----------

  function renderReport(report) {
    els.report.innerHTML = "";
    if (!report) {
      els.report.hidden = true;
      return;
    }
    els.report.hidden = false;

    if (report.stats && report.stats.length) {
      const grid = el("div", "stats");
      for (const s of report.stats) {
        const tile = el("div", "stat");
        tile.appendChild(el("div", "value", String(s.value)));
        tile.appendChild(el("div", "label", s.label));
        grid.appendChild(tile);
      }
      els.report.appendChild(grid);
    }

    if (report.histogram && report.histogram.bins && report.histogram.bins.length) {
      els.report.appendChild(renderHistogram(report.histogram));
    }

    for (const [i, table] of (report.tables || []).entries()) {
      els.report.appendChild(renderTable(table, i === 0));
    }
  }

  function renderHistogram(h) {
    const wrap = el("div", "hist");
    wrap.appendChild(el("h3", null, h.title || t("histogram")));
    const bars = el("div", "hist-bars");
    const max = Math.max(1, ...h.bins.map((b) => b.count));
    const unit = h.unit ? " " + h.unit : "";
    for (const b of h.bins) {
      const bar = el("div", "hist-bar" + (b.count ? "" : " empty"));
      const fill = el("div", "fill");
      fill.style.height = Math.round((100 * b.count) / max) + "%";
      bar.appendChild(fill);
      bar.appendChild(el("div", "tip", `${b.lo}–${b.hi}${unit}: ${b.count} (${b.percent}%)`));
      bars.appendChild(bar);
    }
    wrap.appendChild(bars);
    const axis = el("div", "hist-axis");
    axis.appendChild(el("span", null, `${h.bins[0].lo}${unit}`));
    axis.appendChild(el("span", null, `${h.bins[h.bins.length - 1].hi}${unit}`));
    wrap.appendChild(axis);
    return wrap;
  }

  function renderTable(tbl, open) {
    const details = document.createElement("details");
    if (open) details.open = true;
    details.appendChild(el("summary", null, tbl.title || t("table")));
    const scroller = el("div", "table-wrap");
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (const c of tbl.columns || []) hr.appendChild(el("th", null, c));
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const row of tbl.rows || []) {
      const tr = document.createElement("tr");
      for (const cell of row) tr.appendChild(el("td", null, cell == null ? "" : String(cell)));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scroller.appendChild(table);
    details.appendChild(scroller);
    return details;
  }

  // ---------- viewer ----------

  function loadImage(img, url) {
    return new Promise((resolve, reject) => {
      if (!url) {
        img.removeAttribute("src");
        resolve(false);
        return;
      }
      img.onload = () => resolve(true);
      img.onerror = () => reject(new Error(t("image_load_failed")));
      img.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
    });
  }

  function clearViewer() {
    els.imgOriginal.removeAttribute("src");
    els.imgProcessed.removeAttribute("src");
    els.toolbar.hidden = true;
    els.placeholder.hidden = false;
  }

  async function showImages(originalUrl, processedUrl, keepView) {
    const [hasOriginal, hasProcessed] = await Promise.all([
      loadImage(els.imgOriginal, originalUrl),
      loadImage(els.imgProcessed, processedUrl),
    ]);
    if (!hasOriginal && !hasProcessed) {
      clearViewer();
      return;
    }
    const ref = hasOriginal ? els.imgOriginal : els.imgProcessed;
    const sameSize =
      state.image.width === ref.naturalWidth && state.image.height === ref.naturalHeight;
    state.image = { width: ref.naturalWidth, height: ref.naturalHeight };
    for (const img of [els.imgOriginal, els.imgProcessed]) {
      img.style.width = state.image.width + "px";
      img.style.height = state.image.height + "px";
    }
    els.stage.style.width = state.image.width + "px";
    els.stage.style.height = state.image.height + "px";
    els.placeholder.hidden = true;
    els.toolbar.hidden = false;
    els.toggle.hidden = !hasProcessed;
    state.showProcessed = hasProcessed;
    updateLayers();
    // Re-processing the same picture keeps the user's zoom and position.
    if (keepView && sameSize && state.view.scale > 0 && els.stage.style.transform) applyView();
    else fitToViewport();
  }

  function updateLayers() {
    const hasProcessed = els.imgProcessed.hasAttribute("src");
    const showProcessed = state.showProcessed && !state.holdOriginal && hasProcessed;
    els.imgProcessed.classList.toggle("hidden", !showProcessed);
    els.toggle.textContent = state.showProcessed ? t("hide_processed") : t("show_processed");
    els.toggle.classList.toggle("off", !state.showProcessed);
    els.layerLabel.textContent = !hasProcessed ? t("original") : showProcessed ? t("processed") : t("original");
  }

  function applyView() {
    const { x, y, scale } = state.view;
    els.stage.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    els.zoomLevel.textContent = Math.round(scale * 100) + "%";
  }

  function fitToViewport() {
    const vw = els.viewport.clientWidth;
    const vh = els.viewport.clientHeight;
    const { width, height } = state.image;
    if (!width || !height) return;
    const scale = Math.min(vw / width, vh / height, 1) * 0.98;
    state.view = { scale, x: (vw - width * scale) / 2, y: (vh - height * scale) / 2 };
    applyView();
  }

  function zoomTo(scale, px, py) {
    const clamped = Math.min(32, Math.max(0.02, scale));
    const ratio = clamped / state.view.scale;
    state.view.x = px - (px - state.view.x) * ratio;
    state.view.y = py - (py - state.view.y) * ratio;
    state.view.scale = clamped;
    applyView();
  }

  els.viewport.addEventListener(
    "wheel",
    (e) => {
      if (!state.image.width) return;
      e.preventDefault();
      const rect = els.viewport.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015));
      zoomTo(state.view.scale * factor, e.clientX - rect.left, e.clientY - rect.top);
    },
    { passive: false }
  );

  let drag = null;
  els.viewport.addEventListener("pointerdown", (e) => {
    if (!state.image.width || e.button !== 0) return;
    drag = { startX: e.clientX, startY: e.clientY, x: state.view.x, y: state.view.y };
    els.viewport.setPointerCapture(e.pointerId);
    els.viewport.classList.add("dragging");
  });
  els.viewport.addEventListener("pointermove", (e) => {
    if (!drag) return;
    state.view.x = drag.x + (e.clientX - drag.startX);
    state.view.y = drag.y + (e.clientY - drag.startY);
    applyView();
  });
  const endDrag = (e) => {
    if (!drag) return;
    drag = null;
    els.viewport.classList.remove("dragging");
    try { els.viewport.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  els.viewport.addEventListener("pointerup", endDrag);
  els.viewport.addEventListener("pointercancel", endDrag);
  els.viewport.addEventListener("dblclick", (e) => {
    if (!state.image.width) return;
    const rect = els.viewport.getBoundingClientRect();
    const target = state.view.scale < 1 ? 1 : state.view.scale * 2;
    zoomTo(target, e.clientX - rect.left, e.clientY - rect.top);
  });

  els.toggle.addEventListener("click", () => {
    state.showProcessed = !state.showProcessed;
    updateLayers();
  });
  els.fit.addEventListener("click", fitToViewport);
  els.zoom100.addEventListener("click", () => {
    zoomTo(1, els.viewport.clientWidth / 2, els.viewport.clientHeight / 2);
  });

  window.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.repeat) return;
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON") return;
    e.preventDefault();
    state.holdOriginal = true;
    updateLayers();
  });
  window.addEventListener("keyup", (e) => {
    if (e.code !== "Space") return;
    state.holdOriginal = false;
    updateLayers();
  });
  window.addEventListener("resize", () => {
    if (state.image.width) fitToViewport();
  });

  // ---------- inputs ----------

  els.mode.addEventListener("change", () => selectMode(els.mode.value));
  els.file.addEventListener("change", () => uploadFile(els.file.files[0]));
  els.run.addEventListener("click", run);

  for (const evt of ["dragenter", "dragover"]) {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("drag");
    });
  }
  for (const evt of ["dragleave", "drop"]) {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("drag");
    });
  }
  els.dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  // ---------- init ----------

  async function init() {
    applyStaticStrings();
    try {
      state.health = await api("/api/health");
      await loadModes();
      if (!state.health.rawtherapee) setStatus(t("rt_missing_warn"), "error");
    } catch (err) {
      setStatus(t("modes_load_failed", { error: err.message }), "error");
    }
    updateRunButton();
  }

  init();
})();

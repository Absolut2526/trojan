let activePcs = {};
let currentTargetPc = null;

// UI Elements
const pcGrid = document.getElementById('pcGrid');
const statOnline = document.getElementById('statOnline');
const btnRefresh = document.getElementById('btnRefresh');
const toastEl = document.getElementById('toast');

// Modals
const modalScreenshot = document.getElementById('modalScreenshot');
const screenshotImg = document.getElementById('screenshotImg');
const screenshotSpinner = document.getElementById('screenshotSpinner');

const modalProcesses = document.getElementById('modalProcesses');
const procsTableBody = document.getElementById('procsTableBody');
const procsSpinner = document.getElementById('procsSpinner');

const modalUrl = document.getElementById('modalUrl');
const inputUrl = document.getElementById('inputUrl');
const btnSubmitUrl = document.getElementById('btnSubmitUrl');
const btnCancelUrl = document.getElementById('btnCancelUrl');

const modalKill = document.getElementById('modalKill');
const inputKillName = document.getElementById('inputKillName');
const btnSubmitKill = document.getElementById('btnSubmitKill');
const btnCancelKill = document.getElementById('btnCancelKill');

const modalRename = document.getElementById('modalRename');
const renameTitle = document.getElementById('renameTitle');
const inputRenameName = document.getElementById('inputRenameName');
const btnSubmitRename = document.getElementById('btnSubmitRename');
const btnCancelRename = document.getElementById('btnCancelRename');
let renameTargetPc = null;

const modalStream = document.getElementById('modalStream');
const streamImg = document.getElementById('streamImg');
const streamSpinner = document.getElementById('streamSpinner');
const streamFps = document.getElementById('streamFps');
let activeStreamPc = null;
let streamFrameCount = 0;
let lastFpsTime = Date.now();
let dashboardSocket = null;

function showToast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.style.borderColor = isError ? 'var(--accent-red)' : 'var(--accent-green)';
  toastEl.style.color = isError ? 'var(--accent-red)' : 'var(--text-main)';
  toastEl.style.display = 'block';
  setTimeout(() => {
    toastEl.style.display = 'none';
  }, 4000);
}

// Modal handling
document.querySelectorAll('.modal-close').forEach(btn => {
  btn.onclick = () => {
    const m = btn.closest('.modal');
    if (m === modalStream) closeStream();
    else m.classList.remove('active');
  };
});

window.onclick = (event) => {
  if (event.target.classList.contains('modal')) {
    if (event.target === modalStream) closeStream();
    else event.target.classList.remove('active');
  }
};

async function fetchPcs() {
  try {
    const res = await fetch('/api/pcs');
    if (res.status === 401) {
      window.location.href = '/login';
      return;
    }
    if (!res.ok) throw new Error('Помилка сервера');
    const data = await res.json();
    activePcs = data;
    renderPcs();
    refreshInputButtons();
  } catch (err) {
    console.error('Fetch PCs error:', err);
  }
}

function getDisplayPcTitle(pcName) {
  if (pcName === 'ALL') return 'ВСІ увімкнені комп\'ютери';
  const badge = document.getElementById(`order-badge-${pcName}`);
  if (badge) {
    return `${badge.textContent} (${pcName})`;
  }
  return pcName;
}

function buildCardHtml(name, orderNum, osName, cpu, ram) {
  const safeName = (name || '').replace(/'/g, "\\'");
  return `
    <div class="pc-card-header">
      <div class="pc-title-box">
        <span class="pc-order-badge" id="order-badge-${name}">№${orderNum}</span>
        <div class="pc-name" id="name-${name}">
          <span class="pc-name-text">🖥 ${name}</span>
          <button class="btn-rename-icon" onclick="openRenameModal('${safeName}', event)" title="Перейменувати комп'ютер">✏️</button>
        </div>
        <div class="pc-badge badge-online" id="badge-${name}">
          <span class="status-dot"></span> Онлайн
        </div>
      </div>
      <div class="pc-stats" id="stats-${name}">
        <span class="stat-pill">ОС: ${osName}</span>
        <span class="stat-pill">CPU: ${cpu}</span>
        <span class="stat-pill">RAM: ${ram}</span>
      </div>
    </div>

    <!-- КНОПКИ КЕРУВАННЯ (ЗВЕРХУ НАД ДЕМОНСТРАЦІЄЮ) -->
    <div class="pc-actions" id="actions-${name}">
      <button class="btn-action" onclick="openProcesses('${name}')" title="Список процесів">📋 Процеси</button>
      <button class="btn-action" onclick="openUrlModal('${name}')" title="Відкрити посилання">🌐 URL</button>
      <button class="btn-action" onclick="openPicModal('${name}')" title="Картинка на весь екран">🖼 Картинка</button>
      <button class="btn-action btn-action-fullscreen" onclick="openStream('${name}')" title="Розгорнути на весь екран">⛶ Екран</button>
      <button class="btn-action btn-action-restart" onclick="confirmRestart('${name}')" title="Перезавантажити ПК">🔄 Рестарт</button>
      <button class="btn-action btn-action-shutdown" onclick="confirmShutdown('${name}')" title="Вимкнути ПК">⏻ Вимкнути</button>
    </div>

    <!-- ДЕМОНСТРАЦІЯ ЕКРАНУ (ПІД КНОПКАМИ КЕРУВАННЯ) -->
    <div class="pc-screen-wrapper clickable" id="screen-wrapper-${name}" onclick="openStream('${name}')" title="Натисніть для збільшення трансляції">
      <div class="screen-loading" id="loader-${name}">
        <div class="spinner-small"></div>
        <span>Очікування трансляції...</span>
      </div>
      <img id="stream-img-${name}" class="pc-stream-image" src="" alt="Трансляція ${name}" style="display:none;" />
      <div class="screen-overlay-expand">⛶ Розгорнути</div>
    </div>
  `;
}

function updateCard(card, name, orderNum, osName, cpu, ram) {
  // Оновлюємо бейдж та заголовок черги
  const badgeEl = document.getElementById(`order-badge-${name}`);
  if (badgeEl && badgeEl.textContent !== `№${orderNum}`) {
    badgeEl.textContent = `№${orderNum}`;
  }

  const nameEl = document.getElementById(`name-${name}`);
  if (nameEl) {
    const safeName = (name || '').replace(/'/g, "\\'");
    nameEl.innerHTML = `
      <span class="pc-name-text">🖥 ${name}</span>
      <button class="btn-rename-icon" onclick="openRenameModal('${safeName}', event)" title="Перейменувати комп'ютер">✏️</button>
    `;
  }

  // Оновлюємо показники навантаження
  const statsEl = document.getElementById(`stats-${name}`);
  if (statsEl) {
    statsEl.innerHTML = `
      <span class="stat-pill">ОС: ${osName}</span>
      <span class="stat-pill">CPU: ${cpu}</span>
      <span class="stat-pill">RAM: ${ram}</span>
    `;
  }
}

function renderPcs() {
  const statDot = document.getElementById('statDot');

  // Фільтруємо ТІЛЬКИ увімкнені комп'ютери (онлайн)
  const onlinePcs = Object.values(activePcs).filter(pc => pc.status === 'online');

  // Сортуємо: хто раніше увімкнувся (connected_at) — той перший у списку
  onlinePcs.sort((a, b) => {
    const timeA = a.connected_at || 0;
    const timeB = b.connected_at || 0;
    if (timeA !== timeB) return timeA - timeB;
    return (a.name || '').localeCompare(b.name || '');
  });

  // Якщо ВСІ комп'ютери вимкнені — показуємо порожній екран без жодного ПК
  if (onlinePcs.length === 0) {
    const existingCards = pcGrid.querySelectorAll('[data-pc-card]');
    existingCards.forEach(card => card.remove());

    if (activeStreamPc) {
      closeStream();
    }

    pcGrid.innerHTML = `
      <div class="empty-state">
        <div style="font-size: 42px; margin-bottom: 12px; opacity: 0.7;">🔌</div>
        <div style="font-weight: 700; font-size: 19px; color: var(--text-main); margin-bottom: 8px;">Усі комп'ютери вимкнені</div>
        <div style="font-size: 14px; color: var(--text-muted);">Комп'ютер автоматично з'явиться тут під першим номером, щойно його увімкнуть.</div>
      </div>
    `;

    statOnline.textContent = 'Онлайн: 0';
    if (statDot) statDot.classList.add('offline');
    return;
  }

  // Прибираємо empty-state, якщо він був активний
  const emptyState = pcGrid.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  if (statDot) statDot.classList.remove('offline');
  statOnline.textContent = `Онлайн: ${onlinePcs.length}`;

  const onlineNamesSet = new Set(onlinePcs.map(p => p.name));

  // Видаляємо картки комп'ютерів, які вимкнулися (офлайн)
  const existingCards = pcGrid.querySelectorAll('[data-pc-card]');
  existingCards.forEach(card => {
    const pcName = card.getAttribute('data-pc-card');
    if (!onlineNamesSet.has(pcName)) {
      card.remove();
      if (activeStreamPc === pcName) {
        closeStream();
        showToast(`Комп'ютер ${pcName} вимкнувся`);
      }
    }
  });

  // Додаємо або оновлюємо картки у порядку підключення
  onlinePcs.forEach((pc, index) => {
    const orderNum = index + 1;
    const name = pc.name;
    const info = pc.info || {};
    const cpu = info.cpu !== undefined ? `${info.cpu}%` : 'н/д';
    const ram = info.ram !== undefined ? `${info.ram}%` : 'н/д';
    const osName = info.os || 'Windows';

    let card = document.getElementById(`pc-card-${name}`);
    if (!card) {
      card = document.createElement('div');
      card.id = `pc-card-${name}`;
      card.setAttribute('data-pc-card', name);
      card.className = 'pc-card pc-card-online';
      card.innerHTML = buildCardHtml(name, orderNum, osName, cpu, ram);
      pcGrid.appendChild(card);
    } else {
      updateCard(card, name, orderNum, osName, cpu, ram);
      // Зберігаємо порядок карток у DOM відповідно до черги
      pcGrid.appendChild(card);
    }
  });
}

// API Command sender
async function sendCommand(pcName, action, params = {}) {
  try {
    const res = await fetch(`/api/pcs/${encodeURIComponent(pcName)}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, params })
    });
    if (res.status === 401) {
      window.location.href = '/login';
      return { status: 'error', message: 'Потрібна авторизація' };
    }
    return await res.json();
  } catch (err) {
    return { status: 'error', message: err.message };
  }
}

// Broadcast API Command sender
async function sendBroadcastCommand(action, params = {}) {
  try {
    const res = await fetch('/api/pcs/broadcast/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, params })
    });
    if (res.status === 401) {
      window.location.href = '/login';
      return { status: 'error', message: 'Потрібна авторизація' };
    }
    return await res.json();
  } catch (err) {
    return { status: 'error', message: err.message };
  }
}

// 📸 Screenshot
window.openScreenshot = async (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('screenshotTitle').textContent = `📸 Знімок екрану: ${getDisplayPcTitle(pcName)}`;
  screenshotImg.style.display = 'none';
  screenshotSpinner.style.display = 'block';
  modalScreenshot.classList.add('active');

  const res = await sendCommand(pcName, 'screenshot');
  screenshotSpinner.style.display = 'none';
  if (res.status === 'ok' && res.image_base64) {
    screenshotImg.src = `data:image/jpeg;base64,${res.image_base64}`;
    screenshotImg.style.display = 'block';
  } else {
    modalScreenshot.classList.remove('active');
    showToast(`Помилка отримання скріншоту: ${res.message || 'Невідома помилка'}`, true);
  }
};

// 📋 Processes
window.openProcesses = async (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('procsTitle').textContent = `📋 Процеси: ${getDisplayPcTitle(pcName)}`;
  procsTableBody.innerHTML = '';
  procsSpinner.style.display = 'block';
  modalProcesses.classList.add('active');

  const res = await sendCommand(pcName, 'list_processes');
  procsSpinner.style.display = 'none';

  if (res.status === 'ok' && res.processes) {
    res.processes.slice(0, 30).forEach(p => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><strong>${p.name}</strong></td>
        <td>${p.pid}</td>
        <td>${p.memory || 0} MB</td>
        <td>${p.cpu || 0}%</td>
        <td>
          <button class="btn btn-danger" style="padding:4px 8px;font-size:11px;" onclick="killSpecificProcess('${pcName}', '${p.name}')">Вбити</button>
        </td>
      `;
      procsTableBody.appendChild(row);
    });
  } else {
    procsTableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;">Не вдалося отримати список процесів: ${res.message}</td></tr>`;
  }
};

window.killSpecificProcess = async (pcName, procName) => {
  if (confirm(`Завершити процес "${procName}" на ${getDisplayPcTitle(pcName)}?`)) {
    const res = await sendCommand(pcName, 'kill_process', { name: procName });
    if (res.status === 'ok') {
      showToast(`Процес ${procName} закрито!`);
      openProcesses(pcName);
    } else {
      showToast(res.message, true);
    }
  }
};

// 🌐 Open URL
window.openUrlModal = (pcName) => {
  if (pcName === 'ALL') {
    const onlineCount = Object.values(activePcs).filter(pc => pc.status === 'online').length;
    if (onlineCount === 0) {
      showToast('Немає увімкнених комп\'ютерів!', true);
      return;
    }
  }
  currentTargetPc = pcName;
  document.getElementById('urlTitle').textContent = pcName === 'ALL'
    ? '🌐 Відкрити URL на ВСІ комп\'ютери'
    : `🌐 Відкрити URL: ${getDisplayPcTitle(pcName)}`;
  inputUrl.value = '';
  modalUrl.classList.add('active');
  inputUrl.focus();
};

btnCancelUrl.onclick = () => modalUrl.classList.remove('active');
btnSubmitUrl.onclick = async () => {
  let url = inputUrl.value.trim();
  if (!url) return;
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    url = 'https://' + url;
  }
  modalUrl.classList.remove('active');

  if (currentTargetPc === 'ALL') {
    showToast(`Відкриття ${url} на ВСІХ увімкнених ПК...`);
    const res = await sendBroadcastCommand('open_url', { url });
    if (res.status === 'ok') {
      showToast(`URL успішно відкрито на ${res.count || 0} ПК!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  } else {
    showToast(`Відкриття ${url} на ${currentTargetPc}...`);
    const res = await sendCommand(currentTargetPc, 'open_url', { url });
    if (res.status === 'ok') {
      showToast(`Успішно відкрито на ${currentTargetPc}!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  }
};

// ❌ Kill Process
window.openKillModal = (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('killTitle').textContent = `❌ Закрити процес: ${getDisplayPcTitle(pcName)}`;
  inputKillName.value = '';
  modalKill.classList.add('active');
  inputKillName.focus();
};

btnCancelKill.onclick = () => modalKill.classList.remove('active');
btnSubmitKill.onclick = async () => {
  const name = inputKillName.value.trim();
  if (!name) return;
  modalKill.classList.remove('active');
  showToast(`Завершення процесу ${name} на ${currentTargetPc}...`);
  const res = await sendCommand(currentTargetPc, 'kill_process', { name });
  if (res.status === 'ok') {
    showToast(`Процес(и) завершено: ${res.killed_count || 1}`);
  } else {
    showToast(`Помилка: ${res.message}`, true);
  }
};

// 🔄 Restart & ⏻ Shutdown
window.confirmRestart = async (pcName) => {
  if (confirm(`Ви впевнені, що хочете ПЕРЕЗАВАНТАЖИТИ ${getDisplayPcTitle(pcName)}?`)) {
    showToast(`Команда перезавантаження надіслана на ${pcName}`);
    const res = await sendCommand(pcName, 'restart');
    if (res.status !== 'ok') showToast(res.message, true);
  }
};

window.confirmShutdown = async (pcName) => {
  if (confirm(`УВАГА! Ви дійсно бажаєте ПОВНІСТЮ ВИМКНУТИ ${getDisplayPcTitle(pcName)}?`)) {
    showToast(`Команда вимкнення надіслана на ${pcName}`);
    const res = await sendCommand(pcName, 'shutdown');
    if (res.status !== 'ok') showToast(res.message, true);
  }
};

// ✏️ Rename PC Modal
window.openRenameModal = (pcName, ev) => {
  if (ev) {
    ev.stopPropagation();
    ev.preventDefault();
  }
  renameTargetPc = pcName;
  if (renameTitle) {
    renameTitle.textContent = `✏️ Перейменувати: ${pcName}`;
  }
  if (inputRenameName) {
    inputRenameName.value = pcName;
  }
  if (modalRename) {
    modalRename.classList.add('active');
    setTimeout(() => {
      inputRenameName.focus();
      inputRenameName.select();
    }, 80);
  }
};

if (btnCancelRename) {
  btnCancelRename.onclick = () => {
    if (modalRename) modalRename.classList.remove('active');
  };
}

async function submitRename() {
  if (!renameTargetPc) return;
  const newName = (inputRenameName.value || '').trim();
  if (!newName) {
    showToast('Введіть нову назву для комп\'ютера', true);
    return;
  }
  if (newName === renameTargetPc) {
    if (modalRename) modalRename.classList.remove('active');
    return;
  }

  if (btnSubmitRename) {
    btnSubmitRename.disabled = true;
    btnSubmitRename.textContent = 'Збереження...';
  }

  try {
    const res = await fetch(`/api/pcs/${encodeURIComponent(renameTargetPc)}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      showToast(data.message || `ПК успішно перейменовано на ${newName}`);
      if (modalRename) modalRename.classList.remove('active');
      if (activeStreamPc === renameTargetPc) {
        activeStreamPc = newName;
      }
      if (currentTargetPc === renameTargetPc) {
        currentTargetPc = newName;
      }
      await fetchPcs();
    } else {
      showToast(data.detail || data.message || 'Помилка при перейменуванні', true);
    }
  } catch (err) {
    showToast('Помилка мережі: ' + err.message, true);
  } finally {
    if (btnSubmitRename) {
      btnSubmitRename.disabled = false;
      btnSubmitRename.textContent = '💾 Зберегти назву';
    }
  }
}

if (btnSubmitRename) {
  btnSubmitRename.onclick = submitRename;
}

if (inputRenameName) {
  inputRenameName.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submitRename();
    }
  });
}

// 🖼 Fullscreen Image Modal (Підтримка фото з галереї або посилання)
const modalPic = document.getElementById('modalPic');
const tabPicFile = document.getElementById('tabPicFile');
const tabPicUrl = document.getElementById('tabPicUrl');
const picFileSection = document.getElementById('picFileSection');
const picUrlSection = document.getElementById('picUrlSection');
const inputPicFile = document.getElementById('inputPicFile');
const picDropzone = document.getElementById('picDropzone');
const picPreviewContainer = document.getElementById('picPreviewContainer');
const picPreviewImg = document.getElementById('picPreviewImg');
const picPreviewName = document.getElementById('picPreviewName');
const btnClearPic = document.getElementById('btnClearPic');
const btnChooseGallery = document.getElementById('btnChooseGallery');
const inputPicUrl = document.getElementById('inputPicUrl');
const inputPicDuration = document.getElementById('inputPicDuration');
const btnCancelPic = document.getElementById('btnCancelPic');
const btnSubmitPic = document.getElementById('btnSubmitPic');

let activePicMode = 'file';
let selectedPicBase64 = null;

function triggerFileInput() {
  setPicMode('file');
  if (inputPicFile) {
    inputPicFile.click();
  }
}

function setPicMode(mode) {
  activePicMode = mode;
  if (mode === 'file') {
    tabPicFile.classList.add('active');
    tabPicUrl.classList.remove('active');
    picFileSection.style.display = 'block';
    picUrlSection.style.display = 'none';
  } else {
    tabPicUrl.classList.add('active');
    tabPicFile.classList.remove('active');
    picUrlSection.style.display = 'block';
    picFileSection.style.display = 'none';
    if (inputPicUrl) inputPicUrl.focus();
  }
}

if (tabPicFile) {
  tabPicFile.onclick = (e) => {
    e.preventDefault();
    setPicMode('file');
    // Якщо фото ще не обрано — одразу відкриваємо системну галерею
    if (!selectedPicBase64) {
      triggerFileInput();
    }
  };
}

if (btnChooseGallery) {
  btnChooseGallery.onclick = (e) => {
    e.preventDefault();
    triggerFileInput();
  };
}

if (tabPicUrl) tabPicUrl.onclick = () => setPicMode('url');

// Обробка файлу з галереї та компресія до Full HD для надшвидкої передачі
function processImageFile(file) {
  if (!file || !file.type.startsWith('image/')) {
    showToast('Будь ласка, оберіть файл зображення (фото)', true);
    return;
  }

  const reader = new FileReader();
  reader.onload = (e) => {
    const img = new Image();
    img.onload = () => {
      // Максимальна роздільна здатність 1920x1080 (збереження пропорцій)
      const MAX_W = 1920;
      const MAX_H = 1080;
      let w = img.width;
      let h = img.height;

      if (w > MAX_W || h > MAX_H) {
        const ratio = Math.min(MAX_W / w, MAX_H / h);
        w = Math.round(w * ratio);
        h = Math.round(h * ratio);
      }

      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);

      // Конвертуємо в оптимізований JPEG 85%
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
      selectedPicBase64 = dataUrl.replace(/^data:image\/[a-z]+;base64,/, '');

      picPreviewImg.src = dataUrl;
      picPreviewName.textContent = file.name || 'Фото з галереї';
      picPreviewContainer.style.display = 'flex';
      picDropzone.style.display = 'none';
      if (btnChooseGallery) btnChooseGallery.style.display = 'none';
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function clearPicPreview() {
  selectedPicBase64 = null;
  if (inputPicFile) inputPicFile.value = '';
  picPreviewImg.src = '';
  picPreviewContainer.style.display = 'none';
  picDropzone.style.display = 'flex';
  if (btnChooseGallery) btnChooseGallery.style.display = 'block';
}

if (btnClearPic) btnClearPic.onclick = clearPicPreview;

if (inputPicFile) {
  inputPicFile.addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) processImageFile(file);
  });
}

// Drag & drop на зону завантаження
if (picDropzone) {
  picDropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    picDropzone.classList.add('dragover');
  });
  picDropzone.addEventListener('dragleave', () => {
    picDropzone.classList.remove('dragover');
  });
  picDropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    picDropzone.classList.remove('dragover');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) processImageFile(file);
  });
}

// Швидкі кнопки тривалості (5с, 10с, 30с, 60с)
document.querySelectorAll('.duration-presets .preset-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.duration-presets .preset-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    inputPicDuration.value = btn.getAttribute('data-sec');
  };
});

if (inputPicDuration) {
  inputPicDuration.addEventListener('input', () => {
    const currentVal = inputPicDuration.value;
    document.querySelectorAll('.duration-presets .preset-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-sec') === currentVal);
    });
  });
}

window.openPicModal = (pcName) => {
  if (pcName === 'ALL') {
    const onlineCount = Object.values(activePcs).filter(pc => pc.status === 'online').length;
    if (onlineCount === 0) {
      showToast('Немає увімкнених комп\'ютерів!', true);
      return;
    }
  }
  currentTargetPc = pcName;
  document.getElementById('picTitle').textContent = pcName === 'ALL' 
    ? '🖼 Показати фото на ВСІ комп\'ютери' 
    : `🖼 Показати фото: ${getDisplayPcTitle(pcName)}`;

  // За замовчуванням відкриваємо режим галереї
  setPicMode('file');
  modalPic.classList.add('active');
};

btnCancelPic.onclick = () => modalPic.classList.remove('active');

btnSubmitPic.onclick = async () => {
  const duration = parseFloat(inputPicDuration.value) || 10;
  let params = { duration };

  if (selectedPicBase64) {
    params.image_base64 = selectedPicBase64;
  } else if (inputPicUrl && inputPicUrl.value.trim()) {
    params.image_url = inputPicUrl.value.trim();
  } else {
    showToast('Будь ласка, оберіть фото з галереї або введіть посилання!', true);
    return;
  }

  modalPic.classList.remove('active');

  if (currentTargetPc === 'ALL') {
    showToast(`Відправляю фото на ВСІ увімкнені ПК (${duration}с)...`);
    const res = await sendBroadcastCommand('show_image', params);
    if (res.status === 'ok') {
      showToast(`Фото успішно виведено на ${res.count || 0} ПК!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  } else {
    showToast(`Відправляю фото на ${currentTargetPc} (${duration}с)...`);
    const res = await sendCommand(currentTargetPc, 'show_image', params);
    if (res.status === 'ok') {
      showToast(`Фото відкрито на ${currentTargetPc}!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  }
};

// ⚡ Broadcast Commands
window.broadcastRestart = async () => {
  const onlineCount = Object.values(activePcs).filter(pc => pc.status === 'online').length;
  if (onlineCount === 0) {
    showToast('Немає увімкнених комп\'ютерів!', true);
    return;
  }
  if (confirm(`⚠️ УВАГА! Ви дійсно бажаєте ПЕРЕЗАВАНТАЖИТИ ВСІ увімкнені комп'ютери (${onlineCount} шт)?`)) {
    showToast('Відправляю команду перезавантаження на всі ПК...');
    const res = await sendBroadcastCommand('restart');
    if (res.status === 'ok') {
      showToast(`Команду перезавантаження надіслано на ${res.count || 0} ПК!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  }
};

window.broadcastShutdown = async () => {
  const onlineCount = Object.values(activePcs).filter(pc => pc.status === 'online').length;
  if (onlineCount === 0) {
    showToast('Немає увімкнених комп\'ютерів!', true);
    return;
  }
  if (confirm(`⚠️ УВАГА! Ви дійсно бажаєте ПОВНІСТЮ ВИМКНУТИ ВСІ увімкнені комп'ютери (${onlineCount} шт)?`)) {
    showToast('Відправляю команду вимкнення на всі ПК...');
    const res = await sendBroadcastCommand('shutdown');
    if (res.status === 'ok') {
      showToast(`Команду вимкнення надіслано на ${res.count || 0} ПК!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  }
};

let currentFps = 12;

window.changeStreamFps = async (fps) => {
  currentFps = fps;
  ['fps5', 'fps12', 'fps20'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = (id === `fps${fps}`) ? 'btn btn-primary' : 'btn btn-secondary';
  });

  if (activeStreamPc) {
    showToast(`Перемикання на ${fps} FPS...`);
    await sendCommand(activeStreamPc, 'start_stream', { fps: currentFps });
  }
};

// 🔴 Live Screen Stream (Демонстрація екрану на весь екран / у модальному вікні)
window.openStream = (pcName) => {
  activeStreamPc = pcName;
  document.getElementById('streamTitle').textContent = `🔴 Демонстрація екрану: ${getDisplayPcTitle(pcName)}`;
  refreshInputButtons();

  // Якщо в картці ПК вже транслюється екран — відображаємо його одразу без затримки
  const cardImg = document.getElementById(`stream-img-${pcName}`);
  if (cardImg && cardImg.src && cardImg.src.startsWith('data:image')) {
    streamImg.src = cardImg.src;
    streamImg.style.display = 'block';
    streamSpinner.style.display = 'none';
  } else {
    streamImg.style.display = 'none';
    streamSpinner.style.display = 'block';
  }

  streamFps.textContent = 'Трансляція активна';
  modalStream.classList.add('active');
};

window.closeStream = () => {
  if (mouseControlEnabled) setMouseControl(false, true);
  if (keyboardCaptureEnabled) setKeyboardCapture(false, true);
  isDragging = false;
  activeStreamPc = null;
  modalStream.classList.remove('active');
  streamImg.src = '';
  streamImg.style.display = 'none';
  streamSpinner.style.display = 'none';
};

// 🖱 Керування мишею віддаленого ПК прямо з трансляції
let mouseControlEnabled = false;
let isDragging = false;
let lastMouseMoveTime = 0;
const MOUSE_MOVE_THROTTLE_MS = 25; // ~40 подій/с: плавно для ока і не забиває канал
const MOUSE_BUTTON_MAP = { 0: 'left', 1: 'middle', 2: 'right' };

// Універсальна відправка керування на активний ПК (миша, клавіатура — будь-яка дія)
function sendControl(action, params = {}) {
  if (!activeStreamPc) return false;
  if (!dashboardSocket || dashboardSocket.readyState !== WebSocket.OPEN) return false;
  dashboardSocket.send(JSON.stringify({
    type: 'control',
    pc: activeStreamPc,
    action,
    params
  }));
  return true;
}

function getRelativeCoords(e) {
  const rect = streamImg.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
    y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
  };
}

function isOverStreamImage(e) {
  const rect = streamImg.getBoundingClientRect();
  return e.clientX >= rect.left && e.clientX <= rect.right &&
         e.clientY >= rect.top && e.clientY <= rect.bottom;
}

// ⌨ Клавіатура віддаленого ПК
let keyboardCaptureEnabled = false;
const heldKeys = new Set();          // затиснуті модифікатори — щоб Shift/Ctrl не "залипали" на ПК
const MODIFIER_TOKENS = new Set(['shift', 'ctrl', 'alt', 'win']);

function isTextInputTarget(target) {
  const tag = target && target.tagName ? String(target.tagName).toLowerCase() : '';
  return tag === 'input' || tag === 'textarea' || !!(target && target.isContentEditable);
}

// e.key -> канонічний токен клієнта (той самий формат, що розуміє client.py)
function keyToken(e) {
  const k = e.key;
  if (!k) return '';
  if (k === ' ' || k === 'Spacebar') return 'space';
  if (k.length === 1) return k;              // літери (у т.ч. кирилиця), цифри, пунктуація
  const map = {
    ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
    Escape: 'esc', Enter: 'enter', Control: 'ctrl', Meta: 'win', OS: 'win',
    PageUp: 'pageup', PageDown: 'pagedown', Del: 'delete', ContextMenu: 'apps'
  };
  return map[k] || k.toLowerCase();
}

function releaseHeldKeys() {
  heldKeys.forEach((key) => sendControl('key_up', { key }));
  heldKeys.clear();
}

function setKeyboardCapture(enabled, silent = false) {
  if (!enabled) releaseHeldKeys();
  keyboardCaptureEnabled = enabled;

  const btn = document.getElementById('btnKeyboard');
  if (btn && !btn.disabled) {
    btn.className = `btn ${enabled ? 'btn-primary' : 'btn-secondary'}`;
    btn.textContent = `⌨ Клавіатура: ${enabled ? 'УВІМК' : 'ВИКЛ'}`;
  }

  if (!silent) {
    showToast(enabled
      ? '⌨ Клавіатура увімкнена: натискання йдуть на ПК (Esc — вимкнути)'
      : '⌨ Клавіатуру вимкнено');
  }
}

window.toggleKeyboard = (silent = false) => setKeyboardCapture(!keyboardCaptureEnabled, silent);

// Надсилає текст цілком — найкраще для кирилиці та довгих рядків
window.sendKeyboardText = () => {
  const input = document.getElementById('inputKeyText');
  if (!input) return;
  const text = input.value;
  if (!text) {
    showToast('Введіть текст, який треба надрукувати на ПК', true);
    return;
  }
  if (!sendControl('key_type', { text })) {
    showToast('Немає активного ПК або з\u0027єднання з сервером', true);
    return;
  }
  showToast(`⌨ Текст надіслано на ${activeStreamPc} (${text.length} симв.)`);
  input.value = '';
};

function pressedModifiers(e) {
  const mods = [];
  if (e.ctrlKey) mods.push('ctrl');
  if (e.altKey) mods.push('alt');
  if (e.metaKey) mods.push('win');
  return mods;
}

// Показуємо помилки, які повертає ПК-клієнт (наприклад, немає бекенду керування мишею)
let lastControlError = { key: '', at: 0 };
function showControlError(pc, message) {
  const key = `${pc}:${message}`;
  const now = Date.now();
  if (key === lastControlError.key && now - lastControlError.at < 8000) return;
  lastControlError = { key, at: now };
  showToast(`🖱 ${pc}: ${message}`, true);
}

function setMouseControl(enabled, silent = false) {
  mouseControlEnabled = enabled;
  isDragging = false;

  const btn = document.getElementById('btnMouseControl');
  if (btn && !btn.disabled) {
    btn.className = `btn ${enabled ? 'btn-primary' : 'btn-secondary'}`;
    btn.textContent = `🖱 Миша: ${enabled ? 'УВІМК' : 'ВИКЛ'}`;
  }
  streamImg.style.cursor = enabled ? 'crosshair' : 'default';

  if (!silent) {
    showToast(enabled
      ? '🖱 Керування мишею увімкнено (Esc — вимкнути)'
      : '🖱 Керування мишею вимкнено');
  }
}

window.toggleMouseControl = (silent = false) => setMouseControl(!mouseControlEnabled, silent);

// Стан кнопок залежить від того, який бекенд керування вводом повідомив ПК-клієнт
function refreshInputButtons() {
  if (!activeStreamPc) return;
  const info = (activePcs[activeStreamPc] && activePcs[activeStreamPc].info) || {};

  const mouseBtn = document.getElementById('btnMouseControl');
  if (mouseBtn) {
    if (info.mouse === null) {
      if (mouseControlEnabled) setMouseControl(false, true);
      mouseBtn.className = 'btn btn-secondary';
      mouseBtn.disabled = true;
      mouseBtn.textContent = '🖱 Миша: Н/Д';
      mouseBtn.title = 'Клієнт на цьому ПК не має бекенду керування мишею — перезберіть або оновіть pc_client';
    } else {
      mouseBtn.disabled = false;
      mouseBtn.textContent = `🖱 Миша: ${mouseControlEnabled ? 'УВІМК' : 'ВИКЛ'}`;
      mouseBtn.title = info.mouse
        ? `Бекенд керування мишею: ${info.mouse}`
        : 'Бекенд керування мишею ще невідомий (чекаємо heartbeat від ПК)';
    }
  }

  const kbBtn = document.getElementById('btnKeyboard');
  if (kbBtn) {
    if (info.keyboard === null) {
      if (keyboardCaptureEnabled) setKeyboardCapture(false, true);
      kbBtn.className = 'btn btn-secondary';
      kbBtn.disabled = true;
      kbBtn.textContent = '⌨ Клавіатура: Н/Д';
      kbBtn.title = 'Клієнт на цьому ПК не має бекенду керування клавіатурою — оновіть pc_client';
    } else {
      kbBtn.disabled = false;
      kbBtn.textContent = `⌨ Клавіатура: ${keyboardCaptureEnabled ? 'УВІМК' : 'ВИКЛ'}`;
      kbBtn.title = info.keyboard
        ? `Бекенд керування клавіатурою: ${info.keyboard}`
        : 'Бекенд керування клавіатурою ще невідомий (чекаємо heartbeat від ПК)';
    }
  }
}

// Рух курсору: працює над картинкою трансляції, а під час перетягування — по всій сторінці
 document.addEventListener('mousemove', (e) => {
  if (!mouseControlEnabled || !activeStreamPc) return;
  if (!isDragging && !isOverStreamImage(e)) return;

  const now = Date.now();
  if (now - lastMouseMoveTime < MOUSE_MOVE_THROTTLE_MS) return;
  lastMouseMoveTime = now;

  const coords = getRelativeCoords(e);
  if (coords) sendControl('mouse_move', coords);
});

// Спершу переводимо курсор у точку натиску, потім тримаємо/відпускаємо кнопку (підтримка drag & drop)
streamImg.addEventListener('mousedown', (e) => {
  if (!mouseControlEnabled) return;
  e.preventDefault();
  isDragging = true;

  const coords = getRelativeCoords(e);
  if (coords) sendControl('mouse_move', coords);
  sendControl('mouse_down', { button: MOUSE_BUTTON_MAP[e.button] || 'left' });
});

// Відпускання ловимо на документі, щоб кнопка не "залипала", якщо мишу відпустили поза вікном
 document.addEventListener('mouseup', (e) => {
  if (!isDragging) return;
  isDragging = false;
  if (!mouseControlEnabled) return;
  sendControl('mouse_up', { button: MOUSE_BUTTON_MAP[e.button] || 'left' });
});

streamImg.addEventListener('contextmenu', (e) => {
  if (mouseControlEnabled) e.preventDefault();
});

streamImg.addEventListener('wheel', (e) => {
  if (!mouseControlEnabled) return;
  e.preventDefault();
  sendControl('mouse_scroll', { delta_y: e.deltaY });
}, { passive: false });

// Клавіші: Esc вимикає керування, решта (у режимі клавіатури) летить на ПК
 document.addEventListener('keydown', (e) => {
  if (!modalStream.classList.contains('active')) return;
  if (isTextInputTarget(e.target)) return;   // не заважаємо писати текст у полі надсилання

  if (e.key === 'Escape') {
    if (mouseControlEnabled || keyboardCaptureEnabled) {
      e.preventDefault();
      if (mouseControlEnabled) setMouseControl(false, true);
      if (keyboardCaptureEnabled) setKeyboardCapture(false, true);
      showToast('🖱⌨ Керування вимкнено');
    }
    return;
  }

  if (!keyboardCaptureEnabled) return;
  e.preventDefault();

  const token = keyToken(e);
  if (!token) return;

  if (MODIFIER_TOKENS.has(token)) {
    if (!heldKeys.has(token)) {
      heldKeys.add(token);
      sendControl('key_down', { key: token });
    }
    return;
  }

  const mods = pressedModifiers(e);
  if (mods.length) {
    sendControl('key_hotkey', { keys: [...mods, token] });    // Ctrl+C, Alt+Tab, Win+D...
    return;
  }
  sendControl('key_press', { key: token });
});

 document.addEventListener('keyup', (e) => {
  if (!keyboardCaptureEnabled || !modalStream.classList.contains('active')) return;
  if (isTextInputTarget(e.target)) return;
  const token = keyToken(e);
  if (MODIFIER_TOKENS.has(token)) {
    e.preventDefault();
    heldKeys.delete(token);
    sendControl('key_up', { key: token });
  }
});

// Якщо вкладка/вікно втратило фокус — відпускаємо затиснуті модифікатори на ПК
window.addEventListener('blur', () => { if (keyboardCaptureEnabled) releaseHeldKeys(); });

// Enter у полі тексту — надіслати текст на ПК
const inputKeyText = document.getElementById('inputKeyText');
if (inputKeyText) {
  inputKeyText.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      window.sendKeyboardText();
    }
  });
}

window.toggleStreamFullscreen = () => {
  const container = document.querySelector('#modalStream .modal-content');
  if (!document.fullscreenElement) {
    if (container.requestFullscreen) {
      container.requestFullscreen();
    }
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    }
  }
};

// WebSocket for real-time dashboard events
function setupDashboardWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
  dashboardSocket = new WebSocket(wsUrl);

  dashboardSocket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'pc_status_change' || data.type === 'stats_update' || data.type === 'pc_renamed') {
        if (data.type === 'pc_renamed') {
          if (activeStreamPc === data.old_name) {
            activeStreamPc = data.new_name;
          }
          if (currentTargetPc === data.old_name) {
            currentTargetPc = data.new_name;
          }
          if (renameTargetPc === data.old_name) {
            renameTargetPc = data.new_name;
          }
        }
        fetchPcs();
      } else if (data.type === 'control_error') {
        showControlError(data.pc, data.message);
      } else if (data.type === 'stream_frame') {
        const pc = data.pc;
        const frame = data.frame;

        // 1. Оновлюємо відеопотік безпосередньо в картці комп'ютера
        const cardImg = document.getElementById(`stream-img-${pc}`);
        const cardLoader = document.getElementById(`loader-${pc}`);
        if (cardImg) {
          cardImg.src = 'data:image/jpeg;base64,' + frame;
          if (cardImg.style.display === 'none') {
            cardImg.style.display = 'block';
            if (cardLoader) cardLoader.style.display = 'none';
          }
        }

        // 2. Якщо користувач відкрив повноекранний перегляд для цього ПК
        if (activeStreamPc === pc) {
          streamSpinner.style.display = 'none';
          streamImg.src = 'data:image/jpeg;base64,' + frame;
          streamImg.style.display = 'block';
          streamFrameCount++;
          const now = Date.now();
          if (now - lastFpsTime >= 1000) {
            streamFps.textContent = `Трансляція активна • ~${streamFrameCount} FPS`;
            streamFrameCount = 0;
            lastFpsTime = now;
          }
        }
      }
    } catch (e) {}
  };

  dashboardSocket.onclose = (event) => {
    if (event && event.code === 1008) {
      window.location.href = '/login';
      return;
    }
    setTimeout(setupDashboardWebSocket, 3000);
  };
}

// Функція виходу з панелі керування
async function logout() {
  try {
    await fetch('/api/logout', { method: 'POST' });
  } catch (err) {
    console.error('Logout error:', err);
  }
  window.location.href = '/login';
}
window.logout = logout;

btnRefresh.onclick = fetchPcs;

// Initialize
fetchPcs();
setupDashboardWebSocket();
setInterval(fetchPcs, 10000);

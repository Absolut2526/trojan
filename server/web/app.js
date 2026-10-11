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

const modalStream = document.getElementById('modalStream');
const streamImg = document.getElementById('streamImg');
const streamSpinner = document.getElementById('streamSpinner');
const streamFps = document.getElementById('streamFps');
let activeStreamPc = null;
let streamFrameCount = 0;
let lastFpsTime = Date.now();

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
    if (!res.ok) throw new Error('Помилка сервера');
    const data = await res.json();
    activePcs = data;
    renderPcs();
  } catch (err) {
    console.error('Fetch PCs error:', err);
  }
}

function buildCardHtml(name, isOnline, osName, cpu, ram) {
  return `
    <div class="pc-card-header">
      <div class="pc-title-box">
        <div class="pc-name">🖥 ${name}</div>
        <div class="pc-badge ${isOnline ? 'badge-online' : 'badge-offline'}" id="badge-${name}">
          ${isOnline ? '<span class="status-dot"></span> Онлайн' : 'Офлайн'}
        </div>
      </div>
      <div class="pc-stats" id="stats-${name}">
        <span class="stat-pill">ОС: ${osName}</span>
        ${isOnline ? `<span class="stat-pill">CPU: ${cpu}</span><span class="stat-pill">RAM: ${ram}</span>` : ''}
      </div>
    </div>

    <!-- КНОПКИ КЕРУВАННЯ (ЗВЕРХУ НАД ДЕМОНСТРАЦІЄЮ) -->
    <div class="pc-actions" id="actions-${name}">
      <button class="btn-action" onclick="openScreenshot('${name}')" ${!isOnline ? 'disabled' : ''} title="Знімок екрану">📸 Скрін</button>
      <button class="btn-action" onclick="openProcesses('${name}')" ${!isOnline ? 'disabled' : ''} title="Список процесів">📋 Процеси</button>
      <button class="btn-action" onclick="openUrlModal('${name}')" ${!isOnline ? 'disabled' : ''} title="Відкрити посилання">🌐 URL</button>
      <button class="btn-action" onclick="openPicModal('${name}')" ${!isOnline ? 'disabled' : ''} title="Картинка на весь екран">🖼 Картинка</button>
      <button class="btn-action btn-action-kill" onclick="openKillModal('${name}')" ${!isOnline ? 'disabled' : ''} title="Закрити процес">❌ Процес</button>
      <button class="btn-action btn-action-fullscreen" onclick="openStream('${name}')" ${!isOnline ? 'disabled' : ''} title="Розгорнути на весь екран">⛶ Екран</button>
      <button class="btn-action btn-action-restart" onclick="confirmRestart('${name}')" ${!isOnline ? 'disabled' : ''} title="Перезавантажити ПК">🔄 Рестарт</button>
      <button class="btn-action btn-action-shutdown" onclick="confirmShutdown('${name}')" ${!isOnline ? 'disabled' : ''} title="Вимкнути ПК">⏻ Вимкнути</button>
    </div>

    <!-- ДЕМОНСТРАЦІЯ ЕКРАНУ (ПІД КНОПКАМИ КЕРУВАННЯ) -->
    <div class="pc-screen-wrapper ${isOnline ? 'clickable' : ''}" id="screen-wrapper-${name}" onclick="${isOnline ? `openStream('${name}')` : ''}" title="${isOnline ? 'Натисніть для збільшення трансляції' : ''}">
      ${isOnline ? `
        <div class="screen-live-badge"><span class="live-dot"></span> LIVE</div>
        <div class="screen-loading" id="loader-${name}">
          <div class="spinner-small"></div>
          <span>Очікування трансляції...</span>
        </div>
        <img id="stream-img-${name}" class="pc-stream-image" src="" alt="Трансляція ${name}" style="display:none;" />
        <div class="screen-overlay-expand">⛶ Розгорнути</div>
      ` : `
        <div class="screen-offline-placeholder">
          <div class="screen-offline-icon">🔌</div>
          <div class="screen-offline-title">Комп'ютер вимкнений</div>
          <div class="screen-offline-sub">Немає трансляції</div>
        </div>
      `}
    </div>
  `;
}

function updateCard(card, name, isOnline, osName, cpu, ram) {
  const wasOnline = card.classList.contains('pc-card-online');
  if (wasOnline !== isOnline) {
    // Статус змінився — оновлюємо верстку для показу трансляції або офлайн заглушки
    card.className = `pc-card ${isOnline ? 'pc-card-online' : 'pc-card-offline'}`;
    card.innerHTML = buildCardHtml(name, isOnline, osName, cpu, ram);
    return;
  }

  // Статус той самий — оновлюємо тільки показники статистики без перезавантаження трансляції
  const statsEl = document.getElementById(`stats-${name}`);
  if (statsEl) {
    statsEl.innerHTML = `
      <span class="stat-pill">ОС: ${osName}</span>
      ${isOnline ? `<span class="stat-pill">CPU: ${cpu}</span><span class="stat-pill">RAM: ${ram}</span>` : ''}
    `;
  }
}

function renderPcs() {
  const keys = Object.keys(activePcs);
  if (keys.length === 0) {
    pcGrid.innerHTML = '<div class="empty-state">Поки немає підключених комп\'ютерів. Запустіть клієнт на ПК клубу.</div>';
    statOnline.textContent = 'Онлайн: 0 / 0';
    return;
  }

  const emptyState = pcGrid.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  let onlineCount = 0;
  keys.sort();

  // Видаляємо картки комп'ютерів, які більше не існують
  const existingCards = pcGrid.querySelectorAll('[data-pc-card]');
  existingCards.forEach(card => {
    const pcName = card.getAttribute('data-pc-card');
    if (!activePcs[pcName]) card.remove();
  });

  keys.forEach(name => {
    const pc = activePcs[name];
    const isOnline = pc.status === 'online';
    if (isOnline) onlineCount++;

    const info = pc.info || {};
    const cpu = info.cpu !== undefined ? `${info.cpu}%` : 'н/д';
    const ram = info.ram !== undefined ? `${info.ram}%` : 'н/д';
    const osName = info.os || 'Windows';

    let card = document.getElementById(`pc-card-${name}`);
    if (!card) {
      card = document.createElement('div');
      card.id = `pc-card-${name}`;
      card.setAttribute('data-pc-card', name);
      card.className = `pc-card ${isOnline ? 'pc-card-online' : 'pc-card-offline'}`;
      card.innerHTML = buildCardHtml(name, isOnline, osName, cpu, ram);
      pcGrid.appendChild(card);
    } else {
      updateCard(card, name, isOnline, osName, cpu, ram);
    }
  });

  statOnline.textContent = `Онлайн: ${onlineCount} / ${keys.length}`;
}

// API Command sender
async function sendCommand(pcName, action, params = {}) {
  try {
    const res = await fetch(`/api/pcs/${encodeURIComponent(pcName)}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, params })
    });
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
    return await res.json();
  } catch (err) {
    return { status: 'error', message: err.message };
  }
}

// 📸 Screenshot
window.openScreenshot = async (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('screenshotTitle').textContent = `📸 Знімок екрану: ${pcName}`;
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
  document.getElementById('procsTitle').textContent = `📋 Процеси: ${pcName}`;
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
  if (confirm(`Завершити процес "${procName}" на ${pcName}?`)) {
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
  currentTargetPc = pcName;
  document.getElementById('urlTitle').textContent = `🌐 Відкрити URL: ${pcName}`;
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
  showToast(`Відкриття ${url} на ${currentTargetPc}...`);
  const res = await sendCommand(currentTargetPc, 'open_url', { url });
  if (res.status === 'ok') {
    showToast(`Успішно відкрито на ${currentTargetPc}!`);
  } else {
    showToast(`Помилка: ${res.message}`, true);
  }
};

// ❌ Kill Process
window.openKillModal = (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('killTitle').textContent = `❌ Закрити процес: ${pcName}`;
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
  if (confirm(`Ви впевнені, що хочете ПЕРЕЗАВАНТАЖИТИ ${pcName}?`)) {
    showToast(`Команда перезавантаження надіслана на ${pcName}`);
    const res = await sendCommand(pcName, 'restart');
    if (res.status !== 'ok') showToast(res.message, true);
  }
};

window.confirmShutdown = async (pcName) => {
  if (confirm(`УВАГА! Ви дійсно бажаєте ПОВНІСТЮ ВИМКНУТИ ${pcName}?`)) {
    showToast(`Команда вимкнення надіслана на ${pcName}`);
    const res = await sendCommand(pcName, 'shutdown');
    if (res.status !== 'ok') showToast(res.message, true);
  }
};

// 🖼 Fullscreen Image Modal
const modalPic = document.getElementById('modalPic');
const inputPicUrl = document.getElementById('inputPicUrl');
const inputPicDuration = document.getElementById('inputPicDuration');
const btnCancelPic = document.getElementById('btnCancelPic');
const btnSubmitPic = document.getElementById('btnSubmitPic');

window.openPicModal = (pcName) => {
  currentTargetPc = pcName;
  document.getElementById('picTitle').textContent = pcName === 'ALL' 
    ? '🖼 Показати картинку на ВСІ комп\'ютери' 
    : `🖼 Показати картинку: ${pcName}`;
  inputPicUrl.value = '';
  inputPicDuration.value = '10';
  modalPic.classList.add('active');
  inputPicUrl.focus();
};

btnCancelPic.onclick = () => modalPic.classList.remove('active');
btnSubmitPic.onclick = async () => {
  const url = inputPicUrl.value.trim();
  const duration = parseFloat(inputPicDuration.value) || 10;
  if (!url) {
    showToast('Введіть посилання на картинку!', true);
    return;
  }
  modalPic.classList.remove('active');

  if (currentTargetPc === 'ALL') {
    showToast(`Відправляю картинку на ВСІ ПК (${duration}с)...`);
    const res = await sendBroadcastCommand('show_image', { image_url: url, duration });
    if (res.status === 'ok') {
      showToast(`Картинку виведено на ${res.count || 0} ПК!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  } else {
    showToast(`Відправляю картинку на ${currentTargetPc} (${duration}с)...`);
    const res = await sendCommand(currentTargetPc, 'show_image', { image_url: url, duration });
    if (res.status === 'ok') {
      showToast(`Картинку відкрито на ${currentTargetPc}!`);
    } else {
      showToast(`Помилка: ${res.message}`, true);
    }
  }
};

// ⚡ Broadcast Commands
window.broadcastRestart = async () => {
  if (confirm('⚠️ УВАГА! Ви дійсно бажаєте ПЕРЕЗАВАНТАЖИТИ ВСІ комп\'ютери клубу?')) {
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
  if (confirm('⚠️ УВАГА! Ви дійсно бажаєте ПОВНІСТЮ ВИМКНУТИ ВСІ комп\'ютери клубу?')) {
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
  document.getElementById('streamTitle').textContent = `🔴 Демонстрація екрану: ${pcName}`;

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
  activeStreamPc = null;
  modalStream.classList.remove('active');
  streamImg.src = '';
  streamImg.style.display = 'none';
  streamSpinner.style.display = 'none';
};

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
  const socket = new WebSocket(wsUrl);

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'pc_status_change' || data.type === 'stats_update') {
        fetchPcs();
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

  socket.onclose = () => {
    setTimeout(setupDashboardWebSocket, 3000);
  };
}

btnRefresh.onclick = fetchPcs;

// Initialize
fetchPcs();
setupDashboardWebSocket();
setInterval(fetchPcs, 10000);

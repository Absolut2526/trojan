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

function renderPcs() {
  const keys = Object.keys(activePcs);
  if (keys.length === 0) {
    pcGrid.innerHTML = '<div class="empty-state">Поки немає підключених комп\'ютерів. Запустіть клієнт на ПК клубу.</div>';
    statOnline.textContent = 'Онлайн: 0 / 0';
    return;
  }

  let onlineCount = 0;
  keys.sort();

  pcGrid.innerHTML = '';
  keys.forEach(name => {
    const pc = activePcs[name];
    const isOnline = pc.status === 'online';
    if (isOnline) onlineCount++;

    const card = document.createElement('div');
    card.className = 'pc-card';

    const info = pc.info || {};
    const cpu = info.cpu !== undefined ? `${info.cpu}%` : 'н/д';
    const ram = info.ram !== undefined ? `${info.ram}%` : 'н/д';
    const osName = info.os || 'Windows';

    card.innerHTML = `
      <div class="pc-card-header">
        <div class="pc-name">🖥 ${name}</div>
        <div class="pc-badge ${isOnline ? 'badge-online' : 'badge-offline'}">
          ${isOnline ? 'Онлайн' : 'Офлайн'}
        </div>
      </div>
      <div class="pc-stats">
        <div class="stat-pill">ОС: ${osName}</div>
        ${isOnline ? `<div class="stat-pill">CPU: ${cpu}</div><div class="stat-pill">RAM: ${ram}</div>` : ''}
      </div>
      <div class="pc-actions">
        <button class="btn btn-stream" onclick="openStream('${name}')" ${!isOnline ? 'disabled' : ''}>🔴 Демонстрація</button>
        <button class="btn btn-secondary" onclick="openScreenshot('${name}')" ${!isOnline ? 'disabled' : ''}>📸 Скріншот</button>
        <button class="btn btn-secondary" onclick="openProcesses('${name}')" ${!isOnline ? 'disabled' : ''}>📋 Процеси</button>
        <button class="btn btn-primary" onclick="openUrlModal('${name}')" ${!isOnline ? 'disabled' : ''}>🌐 Відкрити URL</button>
        <button class="btn btn-warning" onclick="openKillModal('${name}')" ${!isOnline ? 'disabled' : ''}>❌ Закрити процес</button>
        <button class="btn btn-secondary" onclick="confirmRestart('${name}')" ${!isOnline ? 'disabled' : ''}>🔄 Рестарт</button>
        <button class="btn btn-danger" onclick="confirmShutdown('${name}')" ${!isOnline ? 'disabled' : ''}>⏻ Вимкнути</button>
      </div>
    `;
    pcGrid.appendChild(card);
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

// 🔴 Live Screen Stream (Демонстрація екрану)
window.openStream = async (pcName) => {
  activeStreamPc = pcName;
  document.getElementById('streamTitle').textContent = `🔴 Демонстрація екрану: ${pcName}`;
  streamImg.style.display = 'none';
  streamSpinner.style.display = 'block';
  streamFps.textContent = 'Підключення до трансляції...';
  modalStream.classList.add('active');

  const res = await sendCommand(pcName, 'start_stream');
  if (res.status !== 'ok') {
    showToast(`Не вдалося запустити стрім: ${res.message}`, true);
    closeStream();
  }
};

window.closeStream = async () => {
  if (activeStreamPc) {
    const pc = activeStreamPc;
    activeStreamPc = null;
    modalStream.classList.remove('active');
    streamImg.src = '';
    streamImg.style.display = 'none';
    streamSpinner.style.display = 'none';
    await sendCommand(pc, 'stop_stream');
  }
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
      } else if (data.type === 'stream_frame' && data.pc === activeStreamPc) {
        streamSpinner.style.display = 'none';
        streamImg.src = 'data:image/jpeg;base64,' + data.frame;
        streamImg.style.display = 'block';
        streamFrameCount++;
        const now = Date.now();
        if (now - lastFpsTime >= 1000) {
          streamFps.textContent = `Трансляція активна • ~${streamFrameCount} FPS`;
          streamFrameCount = 0;
          lastFpsTime = now;
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

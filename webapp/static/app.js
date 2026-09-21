// Telegram Web App Client Logic
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

// State
let channels = [];
let selectedPreviewChannelId = null;

// Helper to make authenticated API requests
async function api(path, options = {}) {
  const initData = tg?.initData || new URLSearchParams(window.location.search).get('initData') || '';
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `tma ${initData}`,
    ...(options.headers || {})
  };

  try {
    const res = await fetch(path, { ...options, headers });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Произошла ошибка при обращении к серверу');
    }
    return data;
  } catch (err) {
    console.error('API error:', err);
    throw err;
  }
}

// Notification helper
function notify(msg, type = 'info') {
  if (tg?.HapticFeedback) {
    if (type === 'error') tg.HapticFeedback.notificationOccurred('error');
    else tg.HapticFeedback.notificationOccurred('success');
  }
  alert(msg);
}

// --- DOM Elements ---
const elTabs = document.querySelectorAll('.nav-tab');
const elTabContents = document.querySelectorAll('.tab-content');
const elChannelsList = document.getElementById('channels-list');
const elPreviewSelect = document.getElementById('preview-channel-select');
const elPreviewResult = document.getElementById('preview-result');
const elPreviewAlbumGrid = document.getElementById('preview-album-grid');
const elPreviewCaption = document.getElementById('preview-caption-text');
const elPreviewPhotoCount = document.getElementById('preview-photo-count');
const elLogsContainer = document.getElementById('logs-container');
const elGdriveStatus = document.getElementById('gdrive-status-text');
const elModeStatus = document.getElementById('mode-status-text');
const elIndicatorGdrive = document.querySelector('#status-gdrive .status-indicator');
const elIndicatorMode = document.querySelector('#status-mode .status-indicator');
const elConnectionBadge = document.getElementById('connection-badge');

// Modal Elements
const elModal = document.getElementById('channel-modal');
const elModalTitle = document.getElementById('modal-title');
const elModalClose = document.getElementById('modal-close');
const elModalCancel = document.getElementById('modal-cancel');
const elChannelForm = document.getElementById('channel-form');
const elBtnDeleteChannel = document.getElementById('btn-delete-channel');
const elBtnAddChannel = document.getElementById('btn-add-channel');
const elGroupCopyFrom = document.getElementById('group-copy-from');
const elCopySourceSelect = document.getElementById('ch-copy-source');

// Tab Navigation
elTabs.forEach(tab => {
  tab.addEventListener('click', () => {
    elTabs.forEach(t => t.classList.remove('active'));
    elTabContents.forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const targetId = tab.getAttribute('data-tab');
    document.getElementById(targetId)?.classList.add('active');

    if (targetId === 'tab-logs') loadStatusAndLogs();
  });
});

// --- Channels Management ---
async function loadChannels() {
  try {
    elChannelsList.innerHTML = '<div class="loading-spinner">Загрузка каналов...</div>';
    channels = await api('/api/channels');
    renderChannels();
    populatePreviewSelect();
  } catch (err) {
    elChannelsList.innerHTML = `<div class="card" style="color:var(--accent-red)">Ошибка загрузки каналов: ${err.message}</div>`;
  }
}

function renderChannels() {
  if (channels.length === 0) {
    elChannelsList.innerHTML = `
      <div class="card" style="text-align:center; padding: 24px;">
        <p style="color:var(--hint-color); margin-bottom:12px;">Пока нет подключенных каналов.</p>
        <button class="btn-primary" onclick="openChannelModal()">+ Добавить первый канал</button>
      </div>
    `;
    return;
  }

  elChannelsList.innerHTML = channels.map(ch => {
    const isAct = !!ch.is_active;
    const bufCount = ch.current_buffer || 0;
    const bufTarget = ch.buffer_target || 3;
    const bufBadgeClass = bufCount >= bufTarget ? 'badge-active' : 'badge-buffer';

    let scheduleText = '';
    if (ch.schedule_mode === 'exact_times') {
      scheduleText = `Часы: ${ch.exact_times}`;
    } else if (ch.schedule_mode === 'times_per_day') {
      const ppd = ch.posts_per_day || 3;
      scheduleText = `${ppd} раз(а) в сутки`;
    } else {
      const hours = Math.round(ch.interval_minutes / 60 * 10) / 10;
      scheduleText = `Каждые ${hours} ч. (${ch.interval_minutes} мин)`;
    }

    return `
      <div class="channel-card">
        <div class="channel-card-header">
          <div>
            <div class="channel-name">${escapeHtml(ch.title)}</div>
            <div class="channel-sub">${escapeHtml(ch.channel_id)}</div>
          </div>
          <div class="channel-toggle-wrapper">
            <span class="channel-toggle-label ${isAct ? 'active' : 'paused'}" id="status-label-${ch.id}">
              ${isAct ? 'Активен' : 'Пауза'}
            </span>
            <label class="switch" title="${isAct ? 'Приостановить канал' : 'Активировать канал'}">
              <input type="checkbox" id="switch-${ch.id}" ${isAct ? 'checked' : ''} onchange="toggleChannelActive(${ch.id}, this.checked)">
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <div class="channel-meta">
          <div class="meta-pill">
            <span>🕒</span> ${scheduleText}
          </div>
          <div class="meta-pill">
            <span>🖼️</span> ${ch.photos_min}–${ch.photos_max} фото
          </div>
          <div class="meta-pill ${bufBadgeClass}">
            <span>📦</span> Отложка: <b>${bufCount} / ${bufTarget}</b>
          </div>
        </div>

        <div class="channel-card-actions">
          <button class="btn-card-action btn-primary-sm" onclick="triggerPostNow(${ch.id})">
            🚀 Опубликовать сейчас
          </button>
          <button class="btn-card-action btn-ghost" onclick="openChannelModal(${ch.id})">
            ⚙️ Настройки
          </button>
        </div>
      </div>
    `;
  }).join('');
}

window.toggleChannelActive = async function(id, isActive) {
  const label = document.getElementById(`status-label-${id}`);
  if (label) {
    label.textContent = isActive ? 'Активен' : 'Пауза';
    label.className = `channel-toggle-label ${isActive ? 'active' : 'paused'}`;
  }
  try {
    await api(`/api/channels/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: isActive })
    });
    const ch = channels.find(c => c.id === id);
    if (ch) ch.is_active = isActive;
    if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
  } catch (err) {
    if (label) {
      label.textContent = !isActive ? 'Активен' : 'Пауза';
      label.className = `channel-toggle-label ${!isActive ? 'active' : 'paused'}`;
    }
    const sw = document.getElementById(`switch-${id}`);
    if (sw) sw.checked = !isActive;
    notify('Не удалось обновить статус: ' + err.message, 'error');
  }
};

function populatePreviewSelect() {
  elPreviewSelect.innerHTML = '<option value="">-- Выберите канал --</option>' +
    channels.map(ch => `<option value="${ch.id}">${escapeHtml(ch.title)} (${escapeHtml(ch.channel_id)})</option>`).join('');
}

// --- Trigger Actions ---
window.triggerRefill = async function(id) {
  try {
    const res = await api(`/api/channels/${id}/refill`, { method: 'POST' });
    notify(res.message);
    loadChannels();
  } catch (err) {
    notify(err.message, 'error');
  }
};

window.triggerPostNow = async function(id) {
  if (!confirm('Опубликовать пост в канал прямо сейчас?')) return;
  try {
    const res = await api(`/api/channels/${id}/post_now`, { method: 'POST' });
    notify(res.message);
    loadChannels();
  } catch (err) {
    notify(err.message, 'error');
  }
};

// Copy settings from donor channel event
if (elCopySourceSelect) {
  elCopySourceSelect.addEventListener('change', () => {
    const donorId = parseInt(elCopySourceSelect.value, 10);
    if (!donorId) return;
    const donor = channels.find(c => c.id === donorId);
    if (!donor) return;

    document.getElementById('ch-gdrive-folder').value = donor.gdrive_folder_id || '';
    document.getElementById('ch-gdrive-texts').value = donor.gdrive_texts_file_id || '';
    document.getElementById('ch-footer-text').value = donor.footer_text || '';
    document.getElementById('ch-photos-min').value = donor.photos_min || 2;
    document.getElementById('ch-photos-max').value = donor.photos_max || 4;
    document.getElementById('ch-schedule-mode').value = donor.schedule_mode || 'interval';
    document.getElementById('ch-interval').value = donor.interval_minutes || 180;
    document.getElementById('ch-exact-times').value = donor.exact_times || '10:00,15:00,20:00';
    const chPostsPerDay = document.getElementById('ch-posts-per-day');
    if (chPostsPerDay) chPostsPerDay.value = donor.posts_per_day || 3;
    document.getElementById('ch-buffer-target').value = donor.buffer_target || 3;
    document.getElementById('ch-is-active').checked = !!donor.is_active;
    toggleScheduleInputs();
  });
}

// Auto-fetch channel title from Telegram
let isFetchingTitle = false;
async function checkAndAutoFetchTitle() {
  const titleInput = document.getElementById('ch-title');
  const channelIdInput = document.getElementById('ch-channel-id');
  if (!titleInput || !channelIdInput) return;

  const currentTitle = titleInput.value.trim();
  const channelId = channelIdInput.value.trim();

  if (currentTitle === '' && channelId.length >= 3 && !isFetchingTitle) {
    isFetchingTitle = true;
    const originalPlaceholder = titleInput.placeholder;
    titleInput.placeholder = '⏳ Получение названия из Telegram...';
    try {
      const res = await api(`/api/telegram/chat-title?channel_id=${encodeURIComponent(channelId)}`);
      if (res && res.title && titleInput.value.trim() === '') {
        titleInput.value = res.title;
        titleInput.style.borderColor = 'var(--accent-green)';
        setTimeout(() => { titleInput.style.borderColor = ''; }, 2000);
      }
    } catch (err) {
      console.log('Auto-fetch channel title notice:', err.message);
    } finally {
      titleInput.placeholder = originalPlaceholder;
      isFetchingTitle = false;
    }
  }
}

const elChChannelId = document.getElementById('ch-channel-id');
if (elChChannelId) {
  elChChannelId.addEventListener('blur', checkAndAutoFetchTitle);
  elChChannelId.addEventListener('change', checkAndAutoFetchTitle);
}

// --- Modal Add / Edit ---
window.openChannelModal = function(id = null) {
  elChannelForm.reset();
  document.getElementById('channel-db-id').value = id || '';

  if (id) {
    elModalTitle.textContent = 'Настройки канала';
    elBtnDeleteChannel.classList.remove('hidden');
    elGroupCopyFrom?.classList.add('hidden');
    const ch = channels.find(c => c.id === id);
    if (ch) {
      document.getElementById('ch-title').value = ch.title || '';
      document.getElementById('ch-channel-id').value = ch.channel_id || '';
      document.getElementById('ch-gdrive-folder').value = ch.gdrive_folder_id || '';
      document.getElementById('ch-gdrive-texts').value = ch.gdrive_texts_file_id || '';
      document.getElementById('ch-footer-text').value = ch.footer_text || '';
      document.getElementById('ch-photos-min').value = ch.photos_min || 2;
      document.getElementById('ch-photos-max').value = ch.photos_max || 4;
      document.getElementById('ch-schedule-mode').value = ch.schedule_mode || 'interval';
      document.getElementById('ch-interval').value = ch.interval_minutes || 180;
      document.getElementById('ch-exact-times').value = ch.exact_times || '10:00,15:00,20:00';
      const chPostsPerDay = document.getElementById('ch-posts-per-day');
      if (chPostsPerDay) chPostsPerDay.value = ch.posts_per_day || 3;
      document.getElementById('ch-buffer-target').value = ch.buffer_target || 3;
      document.getElementById('ch-is-active').checked = !!ch.is_active;
    }
  } else {
    elModalTitle.textContent = 'Добавить новый канал';
    elBtnDeleteChannel.classList.add('hidden');
    const chPostsPerDay = document.getElementById('ch-posts-per-day');
    if (chPostsPerDay) chPostsPerDay.value = 3;
    if (elGroupCopyFrom && elCopySourceSelect) {
      if (channels.length > 0) {
        elGroupCopyFrom.classList.remove('hidden');
        elCopySourceSelect.innerHTML = '<option value="">-- Выберите канал для копирования настроек --</option>' +
          channels.map(c => `<option value="${c.id}">${escapeHtml(c.title)} (${escapeHtml(c.channel_id)})</option>`).join('');
      } else {
        elGroupCopyFrom.classList.add('hidden');
      }
    }
  }

  toggleScheduleInputs();
  elModal.classList.remove('hidden');
};

function closeModal() {
  elModal.classList.add('hidden');
}

elModalClose.addEventListener('click', closeModal);
elModalCancel.addEventListener('click', closeModal);
elBtnAddChannel.addEventListener('click', () => openChannelModal());

document.getElementById('ch-schedule-mode').addEventListener('change', toggleScheduleInputs);

function toggleScheduleInputs() {
  const mode = document.getElementById('ch-schedule-mode').value;
  const grpInterval = document.getElementById('group-interval');
  const grpExact = document.getElementById('group-exact-times');
  const grpTimesPerDay = document.getElementById('group-times-per-day');

  grpInterval.classList.add('hidden');
  grpExact.classList.add('hidden');
  if (grpTimesPerDay) grpTimesPerDay.classList.add('hidden');

  if (mode === 'exact_times') {
    grpExact.classList.remove('hidden');
  } else if (mode === 'times_per_day') {
    if (grpTimesPerDay) grpTimesPerDay.classList.remove('hidden');
    updateTimesPerDayHint();
  } else {
    grpInterval.classList.remove('hidden');
  }
}

function updateTimesPerDayHint() {
  const input = document.getElementById('ch-posts-per-day');
  const hint = document.getElementById('hint-posts-per-day');
  if (!input || !hint) return;
  const n = parseInt(input.value, 10) || 1;
  const hours = Math.round(24 / n * 10) / 10;
  const mins = Math.round(1440 / n);
  hint.textContent = `${n} постов в сутки ≈ каждые ${hours} ч. (${mins} мин)`;
}

const elPostsPerDay = document.getElementById('ch-posts-per-day');
if (elPostsPerDay) elPostsPerDay.addEventListener('input', updateTimesPerDayHint);

elChannelForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = document.getElementById('channel-db-id').value;

  let titleVal = document.getElementById('ch-title').value.trim();
  const channelIdVal = document.getElementById('ch-channel-id').value.trim();
  if (!titleVal && channelIdVal) {
    await checkAndAutoFetchTitle();
    titleVal = document.getElementById('ch-title').value.trim();
  }

  const postsPerDayVal = parseInt(document.getElementById('ch-posts-per-day')?.value, 10) || 3;

  const payload = {
    title: titleVal,
    channel_id: channelIdVal,
    gdrive_folder_id: document.getElementById('ch-gdrive-folder').value.trim(),
    gdrive_texts_file_id: document.getElementById('ch-gdrive-texts').value.trim(),
    footer_text: document.getElementById('ch-footer-text').value.trim(),
    photos_min: parseInt(document.getElementById('ch-photos-min').value, 10),
    photos_max: parseInt(document.getElementById('ch-photos-max').value, 10),
    schedule_mode: document.getElementById('ch-schedule-mode').value,
    interval_minutes: parseInt(document.getElementById('ch-interval').value, 10),
    exact_times: document.getElementById('ch-exact-times').value.trim(),
    posts_per_day: postsPerDayVal,
    buffer_target: parseInt(document.getElementById('ch-buffer-target').value, 10),
    is_active: document.getElementById('ch-is-active').checked
  };

  try {
    if (id) {
      await api(`/api/channels/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
      notify('Настройки канала сохранены!');
    } else {
      await api('/api/channels', { method: 'POST', body: JSON.stringify(payload) });
      notify('Канал успешно добавлен!');
    }
    closeModal();
    loadChannels();
  } catch (err) {
    notify(err.message, 'error');
  }
});

elBtnDeleteChannel.addEventListener('click', async () => {
  const id = document.getElementById('channel-db-id').value;
  if (!id) return;
  if (!confirm('Вы уверены, что хотите удалить этот канал из автопостера?')) return;

  try {
    await api(`/api/channels/${id}`, { method: 'DELETE' });
    notify('Канал удален.');
    closeModal();
    loadChannels();
  } catch (err) {
    notify(err.message, 'error');
  }
});

// --- Preview Tab & Lightbox ---
let currentPreviewPhotos = [];
let currentLightboxIndex = 0;

const elLightbox = document.getElementById('image-lightbox');
const elLightboxImg = document.getElementById('lightbox-img');
const elLightboxCounter = document.getElementById('lightbox-counter');
const elLightboxClose = document.getElementById('lightbox-close');
const elLightboxPrev = document.getElementById('lightbox-prev');
const elLightboxNext = document.getElementById('lightbox-next');

window.openLightbox = function(index) {
  if (!currentPreviewPhotos || currentPreviewPhotos.length === 0) return;
  currentLightboxIndex = (index >= 0 && index < currentPreviewPhotos.length) ? index : 0;
  updateLightboxView();
  if (elLightbox) {
    elLightbox.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
  if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
};

function closeLightbox() {
  if (!elLightbox) return;
  elLightbox.classList.add('hidden');
  if (elLightboxImg) elLightboxImg.src = '';
  document.body.style.overflow = '';
}

function updateLightboxView() {
  if (!currentPreviewPhotos || currentPreviewPhotos.length === 0 || !elLightboxImg) return;
  const photo = currentPreviewPhotos[currentLightboxIndex];
  if (elLightboxCounter) {
    elLightboxCounter.textContent = `${currentLightboxIndex + 1} / ${currentPreviewPhotos.length}`;
  }

  // Load high-resolution image with fallback
  const highResUrl = (photo.thumbnailLink && photo.thumbnailLink.replace(/=s\d+$/, '=s1600')) || `/api/images/${photo.id}`;
  const fallbackUrl = `/api/images/${photo.id}`;

  elLightboxImg.onerror = () => {
    elLightboxImg.onerror = null;
    elLightboxImg.src = fallbackUrl;
  };
  elLightboxImg.src = highResUrl;

  if (currentPreviewPhotos.length <= 1) {
    if (elLightboxPrev) elLightboxPrev.style.display = 'none';
    if (elLightboxNext) elLightboxNext.style.display = 'none';
  } else {
    if (elLightboxPrev) elLightboxPrev.style.display = 'flex';
    if (elLightboxNext) elLightboxNext.style.display = 'flex';
  }
}

function nextLightboxImage() {
  if (currentPreviewPhotos.length <= 1) return;
  currentLightboxIndex = (currentLightboxIndex + 1) % currentPreviewPhotos.length;
  updateLightboxView();
}

function prevLightboxImage() {
  if (currentPreviewPhotos.length <= 1) return;
  currentLightboxIndex = (currentLightboxIndex - 1 + currentPreviewPhotos.length) % currentPreviewPhotos.length;
  updateLightboxView();
}

if (elLightboxClose) elLightboxClose.addEventListener('click', closeLightbox);
if (elLightboxNext) elLightboxNext.addEventListener('click', (e) => { e.stopPropagation(); nextLightboxImage(); });
if (elLightboxPrev) elLightboxPrev.addEventListener('click', (e) => { e.stopPropagation(); prevLightboxImage(); });

if (elLightbox) {
  elLightbox.addEventListener('click', (e) => {
    if (e.target === elLightbox || e.target.classList.contains('lightbox-stage') || e.target.classList.contains('lightbox-img-wrap')) {
      closeLightbox();
    }
  });

  // Touch swipe support for mobile / Telegram WebApp
  let touchStartX = 0;
  let touchStartY = 0;

  elLightbox.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }
  }, { passive: true });

  elLightbox.addEventListener('touchend', (e) => {
    if (e.changedTouches.length === 1) {
      const diffX = e.changedTouches[0].clientX - touchStartX;
      const diffY = e.changedTouches[0].clientY - touchStartY;
      // If horizontal swipe is greater than 40px and dominant over vertical
      if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 40) {
        if (diffX < 0) {
          nextLightboxImage();
        } else {
          prevLightboxImage();
        }
      }
    }
  }, { passive: true });
}

window.addEventListener('keydown', (e) => {
  if (!elLightbox || elLightbox.classList.contains('hidden')) return;
  if (e.key === 'Escape') closeLightbox();
  else if (e.key === 'ArrowRight') nextLightboxImage();
  else if (e.key === 'ArrowLeft') prevLightboxImage();
});

document.getElementById('btn-generate-preview').addEventListener('click', async () => {
  const channelId = elPreviewSelect.value;
  if (!channelId) {
    notify('Пожалуйста, выберите канал из списка.');
    return;
  }

  selectedPreviewChannelId = channelId;
  elPreviewResult.classList.remove('hidden');
  elPreviewCaption.textContent = 'Сборка поста и генерация случайного набора...';
  elPreviewAlbumGrid.innerHTML = '';

  try {
    const preview = await api(`/api/channels/${channelId}/preview`, { method: 'POST' });
    currentPreviewPhotos = preview.photos || [];

    // Render real photos with dual fallback and full screen click
    const gridClass = preview.photos.length === 1 ? 'album-grid single' : 'album-grid';
    elPreviewAlbumGrid.className = gridClass;
    elPreviewAlbumGrid.innerHTML = preview.photos.map((p, i) => {
      const primaryUrl = (p.thumbnailLink && p.thumbnailLink.replace(/=s\d+$/, '=s800')) || `/api/images/${p.id}`;
      const fallbackUrl = `/api/images/${p.id}`;
      return `
        <div class="album-photo-wrap" onclick="openLightbox(${i})" title="Нажмите, чтобы открыть фото на весь экран">
          <img src="${primaryUrl}"
               alt="${escapeHtml(p.name || `Фото ${i+1}`)}"
               class="preview-photo-img"
               loading="lazy"
               onerror="if(this.src !== '${fallbackUrl}'){ this.src = '${fallbackUrl}'; } else { this.onerror=null; this.parentElement.innerHTML='<div class=\\'photo-placeholder\\'><span>🖼️</span><span style=\\'font-size:10px; margin-top:4px;\\'>${escapeHtml(p.name || 'Фото')}</span></div>'; }" />
        </div>
      `;
    }).join('');

    // Render HTML caption
    elPreviewCaption.innerHTML = preview.caption || '<i style="color:var(--hint-color)">Подпись отсутствует</i>';

  } catch (err) {
    elPreviewCaption.innerHTML = `<span style="color:var(--accent-red)">Ошибка: ${err.message}</span>`;
  }
});

document.getElementById('btn-publish-preview-now').addEventListener('click', async () => {
  if (!selectedPreviewChannelId) return;
  await triggerPostNow(selectedPreviewChannelId);
});

// --- Logs & Status ---
async function loadStatusAndLogs() {
  try {
    const status = await api('/api/status');
    // GDrive status
    if (status.google_drive.connected) {
      elGdriveStatus.textContent = status.google_drive.message;
      elIndicatorGdrive.className = 'status-indicator ok';
    } else {
      elGdriveStatus.textContent = status.google_drive.message;
      elIndicatorGdrive.className = 'status-indicator err';
    }

    // Schedule mode
    if (status.telethon_mtproto.authorized) {
      elModeStatus.textContent = 'Нативная отложка Telegram (MTProto Cloud)';
      elIndicatorMode.className = 'status-indicator ok';
    } else {
      elModeStatus.textContent = 'Локальный кэш-буфер (Bot API)';
      elIndicatorMode.className = 'status-indicator';
    }

    elConnectionBadge.textContent = `Подключено (${status.admin})`;

    // Load logs
    const logs = await api('/api/logs');
    if (logs.length === 0) {
      elLogsContainer.innerHTML = '<div style="color:var(--hint-color); padding: 8px;">Логов пока нет.</div>';
    } else {
      elLogsContainer.innerHTML = logs.map(l => `
        <div class="log-entry ${l.level}">
          <span style="color:var(--hint-color)">[${l.created_at}]</span>
          <b>${l.level}:</b> ${escapeHtml(l.message)}
        </div>
      `).join('');
    }

  } catch (err) {
    elConnectionBadge.textContent = 'Ошибка подключения к API';
  }
}

document.getElementById('btn-refresh').addEventListener('click', () => {
  loadChannels();
  loadStatusAndLogs();
});
document.getElementById('btn-clear-logs-view').addEventListener('click', loadStatusAndLogs);

// Escape HTML helper
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Initial Load
loadChannels();
loadStatusAndLogs();

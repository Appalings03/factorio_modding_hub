/* ============================================================
   Factorio Modding Hub — app.js
   Vanilla JS uniquement, pas de dépendances externes
   ============================================================ */

'use strict';

/* ── Autocomplete ───────────────────────────────────────────── */

function initAutocomplete(inputId, endpoint) {
  const input = document.getElementById(inputId);
  if (!input) return;

  let list = null;
  let debounceTimer = null;
  let selectedIndex = -1;

  function removeList() {
    if (list) { list.remove(); list = null; }
    selectedIndex = -1;
  }

  function buildList(items) {
    removeList();
    if (!items.length) return;

    list = document.createElement('ul');
    list.className = 'autocomplete-list';

    // Positionner sous l'input
    const rect = input.getBoundingClientRect();
    list.style.width  = rect.width + 'px';
    list.style.left   = (rect.left + window.scrollX) + 'px';
    list.style.top    = (rect.bottom + window.scrollY) + 'px';
    list.style.position = 'absolute';

    items.forEach((name, i) => {
      const li = document.createElement('li');
      li.textContent = name;
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = name;
        removeList();
        input.form && input.form.submit();
      });
      list.appendChild(li);
    });

    document.body.appendChild(list);
  }

  function highlightItem(index) {
    if (!list) return;
    const items = list.querySelectorAll('li');
    items.forEach((li, i) => li.classList.toggle('selected', i === index));
  }

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) { removeList(); return; }

    debounceTimer = setTimeout(async () => {
      try {
        const resp = await fetch(`${endpoint}?q=${encodeURIComponent(q)}`);
        if (!resp.ok) return;
        const items = await resp.json();
        buildList(items);
      } catch (e) { /* réseau KO en local → silencieux */ }
    }, 200);
  });

  input.addEventListener('keydown', (e) => {
    if (!list) return;
    const items = list.querySelectorAll('li');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
      highlightItem(selectedIndex);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, -1);
      highlightItem(selectedIndex);
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      input.value = items[selectedIndex].textContent;
      removeList();
      input.form && input.form.submit();
    } else if (e.key === 'Escape') {
      removeList();
    }
  });

  document.addEventListener('click', (e) => {
    if (e.target !== input) removeList();
  });
}

/* ── Filtre de propriétés (page détail) ─────────────────────── */

function initPropFilter(filterId, tableId) {
  const filterInput = document.getElementById(filterId);
  const table = document.getElementById(tableId);
  if (!filterInput || !table) return;

  filterInput.addEventListener('input', () => {
    const q = filterInput.value.trim().toLowerCase();
    const rows = table.querySelectorAll('tbody .prop-row');
    rows.forEach(row => {
      const key = row.dataset.key || '';
      row.style.display = (!q || key.toLowerCase().includes(q)) ? '' : 'none';
    });
  });
}

/* ── Toggle colonnes schéma (page détail) ───────────────────── */

function initSchemaToggle(checkboxId) {
  const cb = document.getElementById(checkboxId);
  if (!cb) return;

  function apply() {
    document.querySelectorAll('.schema-col').forEach(el => {
      el.style.display = cb.checked ? '' : 'none';
    });
  }

  apply();
  cb.addEventListener('change', apply);
}

/* ── Diff toggles (page compare) ────────────────────────────── */

function initDiffToggles() {
  document.querySelectorAll('.diff-toggle').forEach(cb => {
    cb.addEventListener('change', () => {
      const group = cb.dataset.group;
      document.querySelectorAll(`.diff-${group}`).forEach(row => {
        row.style.display = cb.checked ? '' : 'none';
      });
    });
  });
}

/* ── Copie dans le presse-papier ────────────────────────────── */

function initCopyButtons() {
  document.querySelectorAll('.btn-copy').forEach(btn => {
    btn.addEventListener('click', async () => {
      const targetId = btn.dataset.target;
      const target = targetId ? document.getElementById(targetId) : null;
      const text = target ? target.textContent : '';
      if (!text) return;

      try {
        await navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = 'Copié !';
        setTimeout(() => { btn.textContent = orig; }, 1800);
      } catch (e) {
        /* Fallback : sélection manuelle */
        const range = document.createRange();
        range.selectNode(target);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
      }
    });
  });
}

/* ── Confirmation sur liens destructifs ─────────────────────── */

function initConfirmLinks() {
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', (e) => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });
}

/* ── Init globale ────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  // Autocomplete dans le header (toutes les pages)
  initAutocomplete('header-search-input', '/api/autocomplete');
  // Liens avec confirmation
  initConfirmLinks();
  // Copie (si des boutons sont présents)
  initCopyButtons();
});
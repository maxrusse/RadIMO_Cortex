/**
 * Shared page shell behaviour.
 *
 * - Closes the Administration menu on outside click or Escape.
 * - RadimoUI.setDirty(scope, count): registers unsaved edits for a page area.
 *   Elements with data-dirty-for="<scope>" show the count; the browser asks
 *   before leaving while any scope has unsaved edits.
 */
(function () {
  'use strict';

  const dirtyScopes = new Map();

  function t(text) {
    return window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text;
  }

  function renderDirty(scope) {
    const count = dirtyScopes.get(scope) || 0;
    document.querySelectorAll(`[data-dirty-for="${scope}"]`).forEach(element => {
      element.hidden = count === 0;
      const label = count === 1 ? t('1 unsaved change') : `${count} ${t('unsaved changes')}`;
      element.textContent = label;
    });
  }

  function setDirty(scope, count) {
    const value = Math.max(0, Number(count) || 0);
    if (value) {
      dirtyScopes.set(scope, value);
    } else {
      dirtyScopes.delete(scope);
    }
    renderDirty(scope);
  }

  function hasDirty() {
    return dirtyScopes.size > 0;
  }

  window.addEventListener('beforeunload', event => {
    if (!hasDirty()) return;
    event.preventDefault();
    event.returnValue = '';
  });

  document.addEventListener('click', event => {
    document.querySelectorAll('details.system-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('details.system-menu[open]').forEach(menu => {
      menu.removeAttribute('open');
      menu.querySelector('summary')?.focus();
    });
  });

  /** Pick the text for the active UI language (for messages with inserted values). */
  function text(en, de) {
    return window.RadimoI18n?.language === 'en' ? en : de;
  }

  /**
   * Shared notification stack (bottom right). Success/info hide after 5 s,
   * warnings and errors stay until closed.
   * @param {'success'|'info'|'warning'|'error'} kind
   * @param {string} message
   * @param {string} [detail]
   */
  function notify(kind, message, detail = '') {
    let stack = document.getElementById('ui-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'ui-toast-stack';
      stack.className = 'ui-toast-stack';
      stack.setAttribute('role', 'status');
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    const toast = document.createElement('div');
    const tone = ['success', 'info', 'warning', 'error'].includes(kind) ? kind : 'info';
    toast.className = `ui-toast ui-toast--${tone}`;
    toast.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    const body = document.createElement('div');
    body.className = 'ui-toast__body';
    const title = document.createElement('div');
    title.className = 'ui-toast__text';
    title.textContent = t(String(message || ''));
    body.appendChild(title);
    if (detail) {
      const extra = document.createElement('div');
      extra.className = 'ui-toast__detail';
      extra.textContent = t(String(detail));
      body.appendChild(extra);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'ui-toast__close';
    close.setAttribute('aria-label', t('Close'));
    close.textContent = '×';
    close.addEventListener('click', () => toast.remove());
    toast.append(body, close);
    stack.appendChild(toast);
    while (stack.children.length > 4) stack.firstElementChild.remove();
    if (tone === 'success' || tone === 'info') setTimeout(() => toast.remove(), 5000);
    return toast;
  }

  window.RadimoUI = { setDirty, hasDirty, notify, text };
})();

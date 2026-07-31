(function () {
  'use strict';

  const dialogState = new WeakMap();
  const openDialogs = [];
  const dialogSelector = '[role="dialog"], .modal-overlay, .modal-backdrop, .break-popup-overlay';
  const focusableSelector = [
    'button:not([disabled])',
    '[href]',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  function isOpen(dialog) {
    if (!dialog || !dialog.isConnected) return false;
    if (dialog.tagName === 'DIALOG') return dialog.open;
    return dialog.classList.contains('active') || dialog.classList.contains('show');
  }

  function focusables(dialog) {
    return Array.from(dialog.querySelectorAll(focusableSelector)).filter(element => {
      const style = getComputedStyle(element);
      return !element.hidden
        && element.getAttribute('aria-hidden') !== 'true'
        && style.display !== 'none'
        && style.visibility !== 'hidden'
        && element.getClientRects().length > 0;
    });
  }

  function primaryButton(dialog) {
    return dialog.querySelector('[data-dialog-submit], .btn-save:not([disabled]), .btn-success:not([disabled]), .btn-primary:not(.btn-cancel):not([disabled]), #workerSelectConfirm:not([disabled])');
  }

  function cancelButton(dialog) {
    return dialog.querySelector('[data-dialog-close], .btn-cancel, .modal-actions .btn-secondary, .break-popup-actions .btn-secondary');
  }

  function activate(dialog) {
    if (dialogState.get(dialog)?.active) return;
    const state = { active: true, opener: document.activeElement };
    dialogState.set(dialog, state);
    openDialogs.push(dialog);
    dialog.setAttribute('aria-modal', 'true');
    if (!dialog.hasAttribute('role')) dialog.setAttribute('role', 'dialog');
    dialog.querySelectorAll('.status, .worker-select-status, .message').forEach(status => {
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
    });
    requestAnimationFrame(() => {
      if (!isOpen(dialog)) return;
      const initial = dialog.querySelector('[data-initial-focus]:not([disabled])') || focusables(dialog)[0];
      initial?.focus({ preventScroll: true });
    });
  }

  function deactivate(dialog) {
    const state = dialogState.get(dialog);
    if (!state?.active) return;
    state.active = false;
    const index = openDialogs.lastIndexOf(dialog);
    if (index >= 0) openDialogs.splice(index, 1);
    if (state.opener?.isConnected) requestAnimationFrame(() => state.opener.focus({ preventScroll: true }));
  }

  function sync(dialog) {
    if (isOpen(dialog)) activate(dialog);
    else deactivate(dialog);
  }

  function topDialog() {
    for (let index = openDialogs.length - 1; index >= 0; index -= 1) {
      if (isOpen(openDialogs[index])) return openDialogs[index];
    }
    return null;
  }

  function handleTab(event, dialog) {
    const elements = focusables(dialog);
    if (!elements.length) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleEnter(event, dialog) {
    if (event.defaultPrevented || event.altKey) return;
    const target = event.target;
    if (target.matches('textarea, [contenteditable="true"]')) {
      if (!(event.ctrlKey || event.metaKey)) return;
      const submit = primaryButton(dialog);
      if (submit) {
        event.preventDefault();
        submit.click();
      }
      return;
    }
    if (target.matches('button, a')) return;
    if (!target.matches('input, select')) return;

    const fields = focusables(dialog).filter(element => element.matches('input:not([readonly]), select, textarea'));
    const index = fields.indexOf(target);
    const next = index >= 0 ? fields[index + 1] : null;
    if (next) {
      event.preventDefault();
      next.focus();
      if (next.matches('input[type="text"], input[type="password"], input[type="number"]')) next.select();
      return;
    }
    const submit = primaryButton(dialog);
    if (submit) {
      event.preventDefault();
      submit.click();
    }
  }

  document.addEventListener('keydown', event => {
    const dialog = topDialog();
    if (!dialog) return;
    if (event.key === 'Tab') handleTab(event, dialog);
    else if (event.key === 'Enter') handleEnter(event, dialog);
    else if (event.key === 'Escape') {
      const cancel = cancelButton(dialog);
      if (cancel) {
        event.preventDefault();
        event.stopImmediatePropagation();
        cancel.click();
      }
    }
  }, true);

  document.addEventListener('click', event => {
    const dialog = event.target.closest(dialogSelector);
    if (!dialog || event.target !== dialog || !isOpen(dialog)) return;
    cancelButton(dialog)?.click();
  });

  function initialize() {
    document.querySelectorAll(dialogSelector).forEach(sync);
    const observer = new MutationObserver(records => {
      records.forEach(record => {
        if (record.type === 'attributes') sync(record.target);
        record.addedNodes.forEach(node => {
          if (!(node instanceof Element)) return;
          if (node.matches(dialogSelector)) sync(node);
          node.querySelectorAll(dialogSelector).forEach(sync);
        });
      });
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'open'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();

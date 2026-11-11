// Prefer the Clipboard API, retaining the long-used RadIMO copy path for
// internal HTTP pages and browsers that deny the newer API.
(function () {
  'use strict';

  function legacyCopy(text) {
    if (typeof document.execCommand !== 'function') return false;
    const active = document.activeElement;
    const selection = window.getSelection();
    const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i).cloneRange()) : [];
    const inputRange = active && typeof active.selectionStart === 'number'
      ? [active.selectionStart, active.selectionEnd, active.selectionDirection] : null;
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.readOnly = true;
    textarea.tabIndex = -1;
    textarea.style.cssText = 'position:fixed;left:-9999px;top:0;font-size:16px;';
    try {
      (active?.closest('dialog[open]') || document.body).appendChild(textarea);
      textarea.focus({ preventScroll: true });
      textarea.select();
      textarea.setSelectionRange(0, text.length);
      return document.execCommand('copy') === true;
    } catch (_) {
      return false;
    } finally {
      textarea.remove();
      try {
        if (active?.isConnected) active.focus({ preventScroll: true });
        if (selection) {
          selection.removeAllRanges();
          ranges.forEach(range => selection.addRange(range));
        }
        if (inputRange && active?.isConnected) active.setSelectionRange(...inputRange);
      } catch (_) {
        // A UI update may have removed the previous focus/selection target.
      }
    }
  }

  async function copy(text) {
    const value = String(text ?? '');
    if (!value) return false;
    try {
      if (typeof navigator.clipboard?.writeText === 'function') {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch (_) {
      // Try the legacy mechanism when permission or context blocks the API.
    }
    return legacyCopy(value);
  }

  window.RadimoClipboard = { copy };
})();

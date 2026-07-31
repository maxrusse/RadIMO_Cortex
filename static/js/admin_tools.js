(function () {
  'use strict';

  const button = document.getElementById('runtime-reload');
  const message = document.getElementById('runtime-message');
  if (!button || !message) return;

  function isEnglish() {
    return window.RadimoI18n?.language === 'en';
  }

  function show(kind, text) {
    message.className = `runtime-message ${kind}`;
    message.textContent = text;
  }

  button.addEventListener('click', async () => {
    const accepted = confirm(isEnglish()
      ? 'Reload the RadIMO application now? Active requests can finish; Gunicorn starts fresh workers.'
      : 'RadIMO-Anwendung jetzt neu laden? Laufende Anfragen können beendet werden; Gunicorn startet frische Worker.');
    if (!accepted) return;

    button.disabled = true;
    show('', isEnglish() ? 'Requesting reload…' : 'Neuladen wird angefordert…');
    try {
      const response = await fetch('/api/admin/runtime/reload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation: 'reload' })
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `Request failed (${response.status})`);
      show('success', isEnglish()
        ? 'Reload requested. The application remains available.'
        : 'Neuladen angefordert. Die Anwendung bleibt erreichbar.');
    } catch (error) {
      show('error', error.message || (isEnglish() ? 'Reload failed.' : 'Neuladen fehlgeschlagen.'));
    } finally {
      button.disabled = false;
    }
  });
})();

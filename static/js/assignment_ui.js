(function () {
  'use strict';

  async function request(endpoint, options) {
    const response = await fetch(endpoint, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) {
      const error = new Error(data.error || 'Assignment request failed');
      error.status = response.status;
      error.code = data.code || '';
      throw error;
    }
    return data;
  }

  function message(error, options = {}) {
    const english = window.RadimoI18n?.language === 'en';
    const noWorker = error?.code === 'no_worker_available' || error?.status === 404;
    if (noWorker && options.strict) {
      return english
        ? 'No strict worker available. Please use normal mode.'
        : 'Kein passender Mitarbeiter verfügbar. Bitte Normalmodus verwenden.';
    }
    if (noWorker) {
      return english
        ? 'No matching worker is currently available.'
        : 'Aktuell ist kein passender Mitarbeiter verfügbar.';
    }
    return english
      ? 'Assignment is currently unavailable. Please try again.'
      : 'Zuweisung momentan nicht möglich. Bitte erneut versuchen.';
  }

  window.AssignmentUI = { request, message };
})();

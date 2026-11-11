// A horizontal overflow wrapper traps CSS sticky headers. Mirror the two
// header rows outside that wrapper while the full-height table scrolls by.
(function () {
  document.querySelectorAll('.prep-editor .edit-table').forEach(table => {
    const wrapper = table.parentElement;
    const floating = document.createElement('div');
    floating.className = 'prep-floating-header';
    floating.dataset.table = table.id;
    floating.setAttribute('aria-hidden', 'true');
    floating.hidden = true;
    document.body.appendChild(floating);
    let dirty = true;
    let queued = false;

    function rebuild() {
      const clone = table.cloneNode(false);
      clone.removeAttribute('id');
      clone.style.width = `${table.getBoundingClientRect().width}px`;
      clone.style.minWidth = '0';
      clone.style.tableLayout = 'fixed';
      const columns = document.createElement('colgroup');
      const subcells = Array.from(table.tHead.rows[1]?.cells || []);
      let subindex = 0;
      Array.from(table.tHead.rows[0].cells).forEach(cell => {
        for (let index = 0; index < cell.colSpan; index += 1) {
          const source = cell.colSpan === 1 ? cell : subcells[subindex++];
          const col = document.createElement('col');
          col.style.width = `${source.getBoundingClientRect().width}px`;
          columns.appendChild(col);
        }
      });
      clone.appendChild(columns);
      const head = table.tHead.cloneNode(true);
      head.removeAttribute('id');
      head.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
      head.querySelectorAll('[tabindex]').forEach(node => node.tabIndex = -1);
      Array.from(head.rows).forEach((row, index) => {
        row.style.height = `${table.tHead.rows[index].getBoundingClientRect().height}px`;
      });
      clone.appendChild(head);
      floating.replaceChildren(clone);
      dirty = false;
    }

    function update() {
      queued = false;
      if (document.querySelector('.modal-overlay.show, .break-popup-overlay.show, dialog[open]')) {
        floating.hidden = true;
        return;
      }
      const head = table.tHead;
      if (!head || !table.getClientRects().length) {
        floating.hidden = true;
        return;
      }
      const headRect = head.getBoundingClientRect();
      const tableRect = table.getBoundingClientRect();
      floating.hidden = headRect.top >= 0 || tableRect.bottom <= headRect.height;
      if (floating.hidden) return;
      if (dirty) rebuild();
      const rect = wrapper.getBoundingClientRect();
      floating.style.left = `${rect.left + wrapper.clientLeft}px`;
      floating.style.width = `${wrapper.clientWidth}px`;
      floating.style.height = `${headRect.height}px`;
      floating.scrollLeft = wrapper.scrollLeft;
    }

    function schedule() {
      if (!queued) {
        queued = true;
        requestAnimationFrame(update);
      }
    }

    function invalidate() { dirty = true; schedule(); }
    new MutationObserver(invalidate).observe(table, {
      childList: true, subtree: true, characterData: true,
    });
    if (window.ResizeObserver) new ResizeObserver(invalidate).observe(table);
    document.querySelectorAll('.modal-overlay, .break-popup-overlay, dialog').forEach(dialog => {
      new MutationObserver(schedule).observe(dialog, {
        attributes: true, attributeFilter: ['class', 'open'],
      });
    });
    window.addEventListener('scroll', schedule, { capture: true, passive: true });
    window.addEventListener('resize', invalidate);
    schedule();
  });
})();

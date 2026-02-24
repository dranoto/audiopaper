// utils.js - Helper utilities

function showLoading(element, message) {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    if (!element) return;
    element.innerHTML = `<div class="d-flex align-items-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span><span>${message}</span></div>`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function requestNotificationPermission() {
    if (Notification.permission === 'default') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                showNotification('Success!', 'You will now be notified when tasks are complete.');
            }
        });
    }
}

function showNotification(title, body) {
    if (Notification.permission === 'granted') {
        new Notification(title, { body: body });
    }
}

function createTableElement(data) {
    if (!data) return null;

    const table = document.createElement('table');
    table.className = 'table table-bordered table-sm';

    const thead = document.createElement('thead');
    const tbody = document.createElement('tbody');

    const headerRow = data.length > 0 ? data[0] : [];
    const trHead = document.createElement('tr');
    headerRow.forEach(cellText => {
        const th = document.createElement('th');
        th.textContent = cellText || '';
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);

    for (let i = 1; i < data.length; i++) {
        const rowData = data[i];
        const tr = document.createElement('tr');
        rowData.forEach(cellText => {
            const td = document.createElement('td');
            td.textContent = cellText || '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    }

    table.appendChild(thead);
    table.appendChild(tbody);

    const tableContainer = document.createElement('div');
    tableContainer.className = 'table-responsive';
    tableContainer.appendChild(table);

    return tableContainer;
}

function showModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'flex';
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'none';
}

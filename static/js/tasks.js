// tasks.js - Task status functions

function loadTaskStatus(fileId) {
    const section = document.getElementById('task-status-section');
    const list = document.getElementById('task-list');

    if (!section || !list) return;

    fetch(`/ragflow/tasks?file_id=${fileId}`)
        .then(r => r.json())
        .then(data => {
            const tasks = data.tasks || [];

            if (tasks.length === 0) {
                section.style.display = 'none';
                return;
            }

            section.style.display = 'block';

            list.innerHTML = tasks.map(task => {
                const statusIcon = {
                    'pending': '<i class="bi bi-clock"></i>',
                    'queued': '<i class="bi bi-clock"></i>',
                    'processing': '<i class="bi bi-arrow-repeat"></i>',
                    'complete': '<i class="bi bi-check-circle"></i>',
                    'error': '<i class="bi bi-exclamation-circle"></i>',
                    'retrying': '<i class="bi bi-arrow-repeat"></i>'
                }[task.status] || '<i class="bi bi-question-circle"></i>';

                const retryBtn = task.status === 'error'
                    ? `<button class="btn btn-sm btn-outline" onclick="retryTask('${task.id}')">
                        <i class="bi bi-arrow-repeat"></i> Retry
                       </button>`
                    : '';

                return `
                    <div class="task-item ${task.status}">
                        <div class="task-icon">${statusIcon}</div>
                        <div class="task-info">
                            <div class="task-type">${task.task_type || 'Task'}</div>
                            <div class="task-status">${task.status}</div>
                            ${task.error ? `<div class="task-error">${escapeHtml(task.error)}</div>` : ''}
                        </div>
                        <div class="task-retry">${retryBtn}</div>
                    </div>
                `;
            }).join('');
        })
        .catch(err => console.error('Failed to load tasks:', err));
}

function refreshTaskStatus() {
    const fileId = window.CURRENT_FILE_ID;
    if (fileId) {
        loadTaskStatus(fileId);
    }
}

function retryTask(taskId) {
    fetch(`/ragflow/task/${taskId}/retry`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                refreshTaskStatus();
            } else {
                showToast('Failed to retry task: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(err => showToast('Error: ' + err.message, 'error'));
}

function initTaskStatus() {
    if (window.CURRENT_FILE_ID) {
        setTimeout(() => loadTaskStatus(window.CURRENT_FILE_ID), 1000);
    }

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('show_tasks') === 'true') {
        const section = document.getElementById('task-status-section');
        if (section) {
            section.style.display = 'block';
        }
        if (window.CURRENT_FILE_ID) {
            loadTaskStatus(window.CURRENT_FILE_ID);
        }
    }
}

// Expose to window
window.loadTaskStatus = loadTaskStatus;
window.refreshTaskStatus = refreshTaskStatus;
window.retryTask = retryTask;
window.initTaskStatus = initTaskStatus;

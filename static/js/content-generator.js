// content-generator.js - Content generation and task polling

let activePollers = {};

// Expose to window
window.resumePendingTasks = resumePendingTasks;

function getPendingTasks() {
    return JSON.parse(localStorage.getItem('pendingTasks') || '{}');
}

function savePendingTask(fileId, task) {
    const tasks = getPendingTasks();
    tasks[fileId] = task;
    localStorage.setItem('pendingTasks', JSON.stringify(tasks));
}

function removePendingTask(fileId) {
    const tasks = getPendingTasks();
    delete tasks[fileId];
    localStorage.setItem('pendingTasks', JSON.stringify(tasks));
}

function pollTaskStatus(taskUrl, fileId, type) {
    if (activePollers[fileId]) {
        clearInterval(activePollers[fileId]);
    }

    const interval = setInterval(() => {
        fetch(taskUrl)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'complete') {
                    clearInterval(interval);
                    delete activePollers[fileId];
                    removePendingTask(fileId);
                    updateFileContent(fileId);
                    showNotification(`${type} Generation Complete`, `The ${type.toLowerCase()} for your file is ready.`);
                    updateButtonState(fileId, type, 'complete');
                } else if (data.status === 'error') {
                    clearInterval(interval);
                    delete activePollers[fileId];
                    removePendingTask(fileId);
                    showGenerationError(fileId, type, data.result?.error);
                }
            })
            .catch(err => {
                clearInterval(interval);
                delete activePollers[fileId];
                handlePollingError(fileId, type, err);
            });
    }, 2000);

    activePollers[fileId] = interval;
}

function updateButtonState(fileId, type, status) {
    const fileItem = document.getElementById(`file-item-${fileId}`);
    if (!fileItem) return;

    let button, text, removeClass, addClass;

    if (type === 'Summary') {
        button = fileItem.querySelector('[data-action="summarizeFile"]');
        text = 'Re-summarize';
        removeClass = 'btn-outline-secondary';
        addClass = 'btn-outline-success';
    } else if (type === 'Transcript') {
        button = fileItem.querySelector('[data-action="generateTranscript"]');
        text = 'Re-generate Transcript';
        removeClass = 'btn-outline-primary';
        addClass = 'btn-outline-success';
    } else if (type === 'Podcast') {
        button = fileItem.querySelector('[data-action="generatePodcast"]');
        text = 'Re-generate Podcast';
        removeClass = 'btn-outline-secondary';
        addClass = 'btn-outline-success';
    }

    if (button) {
        button.textContent = text;
        button.classList.remove(removeClass);
        button.classList.add(addClass);
    }

    if (type === 'Transcript') {
        const podcastButton = fileItem.querySelector('.podcast-button');
        if (podcastButton) podcastButton.disabled = false;
    }
}

function showGenerationError(fileId, type, error) {
    let contentEl;
    if (type === 'Summary') {
        contentEl = document.getElementById('summary-content');
    } else if (type === 'Transcript') {
        contentEl = document.getElementById('transcript-content');
    } else if (type === 'Podcast') {
        const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
        if (button) {
            button.innerHTML = 'Podcast';
            button.disabled = false;
        }
    }

    if (contentEl) {
        contentEl.innerHTML = `<p class="text-danger">Error: ${error || 'Unknown error'}</p>`;
    }

    const errorMessage = error || 'Unknown error';
    showNotification(`${type} Generation Failed`, `There was an error generating the ${type.toLowerCase()}: ${errorMessage}`);
}

function handlePollingError(fileId, type, err) {
    let contentEl;
    if (type === 'Summary') {
        contentEl = document.getElementById('summary-content');
    } else if (type === 'Transcript') {
        contentEl = document.getElementById('transcript-content');
    } else if (type === 'Podcast') {
        showNotification('Polling Error', `An error occurred while checking the podcast status: ${err.message}`);
        const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
        if (button) {
            button.innerHTML = 'Podcast';
            button.disabled = false;
        }
    }

    if (contentEl) {
        contentEl.innerHTML = `<p class="text-danger">Error polling for status: ${err.message}. Please reload the page to retry.</p>`;
    }
}

function summarizeFile(fileId) {
    showLoading(document.getElementById('summary-content'), 'Generating summary... This may take a moment.');
    const summaryTab = document.getElementById('summary-tab');
    if (summaryTab) {
        new bootstrap.Tab(summaryTab).show();
    }
    requestNotificationPermission();

    fetch(`/summarize_file/${fileId}`, { method: 'POST' })
        .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start summary generation.');
            }
        })
        .then(data => {
            const taskUrl = `/summarize_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Summary' });
            pollTaskStatus(taskUrl, fileId, 'Summary');
        })
        .catch(err => {
            document.getElementById('summary-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        });
}

function generateTranscript(fileId) {
    showLoading(document.getElementById('transcript-content'), 'Generating transcript... This may take a moment.');
    const transcriptTab = document.getElementById('transcript-tab');
    if (transcriptTab) {
        new bootstrap.Tab(transcriptTab).show();
    }
    requestNotificationPermission();

    fetch(`/generate_transcript/${fileId}`, { method: 'POST' })
        .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start transcript generation.');
            }
        })
        .then(data => {
            const taskUrl = `/transcript_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Transcript' });
            pollTaskStatus(taskUrl, fileId, 'Transcript');
        })
        .catch(err => {
            document.getElementById('transcript-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        });
}

function generatePodcast(fileId) {
    const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
    button.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...`;
    button.disabled = true;
    requestNotificationPermission();

    fetch(`/generate_podcast/${fileId}`, { method: 'POST' })
        .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start podcast generation.');
            }
        })
        .then(data => {
            const taskUrl = `/podcast_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Podcast' });
            pollTaskStatus(taskUrl, fileId, 'Podcast');
        })
        .catch(err => {
            showNotification('Podcast Error', 'Error starting podcast generation: ' + err.message);
            button.innerHTML = 'Podcast';
            button.disabled = false;
        });
}

function resumePendingTasks() {
    const pendingTasks = getPendingTasks();
    for (const fileId in pendingTasks) {
        const task = pendingTasks[fileId];
        pollTaskStatus(task.taskUrl, fileId, task.type);
    }
}

// Expose to window
window.summarizeFile = summarizeFile;
window.generateTranscript = generateTranscript;
window.generatePodcast = generatePodcast;
window.updateFileContent = window.updateFileContent || updateFileContent;

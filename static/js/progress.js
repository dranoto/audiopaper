// progress.js - Progress modals and inline progress

const taskStepMap = {
    'summary': { step: 2, name: 'Summary', icon: 'bi-card-text' },
    'transcript': { step: 3, name: 'Script', icon: 'bi-chat-dots' },
    'podcast': { step: 4, name: 'Audio', icon: 'bi-headphones' }
};

let isGenerating = false;
let currentEventSource = null;
let currentTaskInterval = null;
let globalInlineMode = false;

function showProgressModal(taskType, message) {
    if (globalInlineMode) {
        const inlineDiv = document.getElementById('inline-progress');
        if (inlineDiv !== null) {
            showLoading(message, taskType);
            return;
        }
    }

    const modal = document.getElementById('progress-modal');
    const title = document.getElementById('progress-title');
    const subtitle = document.getElementById('progress-subtitle');
    const icon = document.getElementById('progress-icon');
    const bar = document.getElementById('progress-bar');
    const status = document.getElementById('progress-status');
    const cancelBtn = document.getElementById('progress-cancel');
    const steps = document.querySelectorAll('.progress-step');

    const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType, icon: 'bi-gear' };

    title.textContent = message || `Generating ${taskInfo.name}...`;
    subtitle.textContent = taskInfo.name;

    icon.className = 'progress-icon processing';
    icon.innerHTML = `<i class="bi ${taskInfo.icon}"></i>`;

    bar.className = 'progress-bar';
    bar.style.width = '10%';

    steps.forEach((s, i) => {
        s.className = 'progress-step';
        if (i + 1 < taskInfo.step) {
            s.classList.add('completed');
        } else if (i + 1 === taskInfo.step) {
            s.classList.add('active');
        }
    });

    status.textContent = `Step ${taskInfo.step} of 4`;
    cancelBtn.style.display = 'inline-flex';

    modal.classList.remove('hidden');
}

function updateProgress(taskType, progress, message) {
    const bar = document.getElementById('progress-bar');
    const title = document.getElementById('progress-title');
    const status = document.getElementById('progress-status');

    if (progress !== undefined) {
        bar.style.width = progress + '%';
    }
    if (message) {
        title.textContent = message;
    }
}

function showProgressSuccess(taskType) {
    const modal = document.getElementById('progress-modal');
    const title = document.getElementById('progress-title');
    const subtitle = document.getElementById('progress-subtitle');
    const icon = document.getElementById('progress-icon');
    const bar = document.getElementById('progress-bar');
    const cancelBtn = document.getElementById('progress-cancel');

    const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType };

    title.textContent = `${taskInfo.name} Complete!`;
    subtitle.textContent = 'Redirecting...';
    icon.className = 'progress-icon success';
    icon.innerHTML = '<i class="bi bi-check-lg"></i>';
    bar.className = 'progress-bar success';
    bar.style.width = '100%';
    cancelBtn.style.display = 'none';

    setTimeout(() => {
        modal.classList.add('hidden');
        const url = new URL(window.location);
        const fileId = url.searchParams.get('file');
        const newUrl = fileId ? `/?file=${fileId}` : '/';
        window.location.href = newUrl;
    }, 1500);
}

function showProgressError(taskType, error) {
    const modal = document.getElementById('progress-modal');
    const title = document.getElementById('progress-title');
    const subtitle = document.getElementById('progress-subtitle');
    const icon = document.getElementById('progress-icon');
    const bar = document.getElementById('progress-bar');
    const cancelBtn = document.getElementById('progress-cancel');

    const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType };

    title.textContent = 'Error';
    subtitle.textContent = error || 'An error occurred';
    icon.className = 'progress-icon error';
    icon.innerHTML = '<i class="bi bi-exclamation-lg"></i>';
    bar.className = 'progress-bar error';
    bar.style.width = '100%';
    cancelBtn.textContent = 'Close';
    cancelBtn.onclick = () => modal.classList.add('hidden');
}

function hideProgressModal() {
    document.getElementById('progress-modal').classList.add('hidden');
}

function showInlineSuccess(type) {
    const barEl = document.getElementById('inline-progress-bar');
    const statusEl = document.getElementById('progress-status-text');
    if (barEl) {
        barEl.className = 'progress-bar success';
        barEl.style.width = '100%';
    }
    if (statusEl) statusEl.textContent = 'Complete! Loading...';
    isGenerating = false;
    setTimeout(() => window.location.reload(), 1000);
}

function showInlineError(type, error) {
    const barEl = document.getElementById('inline-progress-bar');
    const statusEl = document.getElementById('progress-status-text');
    if (barEl) {
        barEl.className = 'progress-bar error';
        barEl.style.width = '100%';
    }
    if (statusEl) statusEl.textContent = 'Error: ' + error;
    resetGenerateButton(type);
}

function showLoading(text, type = 'summary') {
    const inlineDiv = document.getElementById('inline-progress');
    const hasInlineElements = inlineDiv !== null;
    const useInline = globalInlineMode && hasInlineElements;

    if (useInline) {
        const stepNumEl = document.getElementById('progress-step-num');
        const titleEl = document.getElementById('progress-title-text');
        const statusEl = document.getElementById('progress-status-text');
        const barEl = document.getElementById('inline-progress-bar');

        const taskInfo = taskStepMap[type] || { step: 2, name: type };

        if (stepNumEl) stepNumEl.textContent = taskInfo.step;
        if (titleEl) titleEl.textContent = text;
        if (statusEl) statusEl.textContent = 'Please wait...';
        if (barEl) {
            barEl.classList.remove('success', 'error');
            barEl.style.width = '10%';
        }

        if (inlineDiv) {
            inlineDiv.style.display = 'block';
        }

        const modal = document.getElementById('progress-modal');
        if (modal) modal.classList.add('hidden');
        return;
    }

    showProgressModal(type, text);
}

function hideLoading() {}

function cancelCurrentTask() {
    if (currentTaskInterval) {
        clearInterval(currentTaskInterval);
        currentTaskInterval = null;
    }
    hideProgressModal();
}

function pollTask(taskId, type, inline = null) {
    if (inline === null) {
        inline = globalInlineMode;
    }

    const statusType = (type === 'summary') ? 'summarize' : type;

    const hasInlineElements = document.getElementById('inline-progress') !== null;
    if (inline && !hasInlineElements) {
        inline = false;
    }

    if (inline) {
        const inlineDiv = document.getElementById('inline-progress');
        if (inlineDiv) inlineDiv.style.display = 'block';

        const stepNumEl = document.getElementById('progress-step-num');
        const taskInfo = taskStepMap[type] || { step: 2, name: type };
        if (stepNumEl) stepNumEl.textContent = taskInfo.step;

        const titleEl = document.getElementById('progress-title-text');
        const statusEl = document.getElementById('progress-status-text');
        const barEl = document.getElementById('inline-progress-bar');
        if (titleEl) titleEl.textContent = `Generating ${taskStepMap[type]?.name || type}...`;
        if (statusEl) statusEl.textContent = 'Please wait while we analyze the paper...';
        if (barEl) barEl.style.width = '10%';
    } else {
        showProgressModal(type, `Generating ${taskStepMap[type]?.name || type}...`);
    }

    currentTaskInterval = setInterval(() => {
        fetch('/' + statusType + '_status/' + taskId)
            .then(r => r.json())
            .then(data => {
                if (data.status === 'complete') {
                    clearInterval(currentTaskInterval);
                    currentTaskInterval = null;
                    if (inline) {
                        showInlineSuccess(type);
                    } else {
                        showProgressSuccess(type);
                    }
                } else if (data.status === 'error') {
                    clearInterval(currentTaskInterval);
                    currentTaskInterval = null;
                    if (inline) {
                        showInlineError(type, data.result?.error || 'Unknown error');
                    } else {
                        showProgressError(type, data.result?.error || 'Unknown error');
                    }
                } else {
                    if (inline) {
                        const barEl = document.getElementById('inline-progress-bar');
                        const current = parseInt(barEl?.style.width) || 10;
                        if (barEl && current < 85) {
                            barEl.style.width = (current + 15) + '%';
                        }
                    }
                }
            });
    }, 2000);
}

function resetGenerateButton(type) {
    let btnId = null;
    if (type === 'summary') btnId = 'btn-generate-summary';
    else if (type === 'transcript') btnId = 'btn-generate-transcript';
    else if (type === 'podcast') btnId = 'btn-generate-audio';

    if (btnId) {
        const btn = document.getElementById(btnId);
        if (btn) {
            btn.disabled = false;
            if (type === 'summary') {
                btn.innerHTML = '<i class="bi bi-lightning"></i> Generate Summary';
            } else if (type === 'transcript') {
                btn.innerHTML = '<i class="bi bi-chat-dots"></i> Generate Podcast Script';
            } else if (type === 'podcast') {
                btn.innerHTML = '<i class="bi bi-play-circle"></i> Generate Audio';
            }
        }
    }
    isGenerating = false;
}

function streamSummary() {
    if (isGenerating) return;
    isGenerating = true;

    const btn = document.getElementById('btn-generate-summary');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
    }

    globalInlineMode = true;
    showLoading('Generating summary...');

    if (currentEventSource) {
        currentEventSource.close();
    }

    const statusEl = document.getElementById('progress-status-text');
    const barEl = document.getElementById('inline-progress-bar');
    let fullText = '';

    const fileId = window.CURRENT_FILE_ID;
    currentEventSource = new EventSource(`/summarize_stream/${fileId}`);

    currentEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.type === 'token') {
            fullText += data.content;
            if (barEl && fullText.length > 50) {
                const progress = Math.min(10 + (fullText.length / 10), 90);
                barEl.style.width = progress + '%';
            }
            if (statusEl) {
                statusEl.textContent = `Generating... ${fullText.length} chars`;
            }
        } else if (data.type === 'complete') {
            currentEventSource.close();
            currentEventSource = null;
            if (barEl) {
                barEl.className = 'progress-bar success';
                barEl.style.width = '100%';
            }
            if (statusEl) statusEl.textContent = 'Complete! Loading...';
            setTimeout(() => window.location.reload(), 1000);
        } else if (data.type === 'error') {
            currentEventSource.close();
            currentEventSource = null;
            isGenerating = false;
            resetGenerateButton('summary');
            showInlineError('summary', data.error);
        }
    };

    currentEventSource.onerror = function() {
        currentEventSource.close();
        currentEventSource = null;
        showInlineError('summary', 'Connection error');
    };
}

function streamTranscript() {
    if (isGenerating) return;
    isGenerating = true;

    const btn = document.getElementById('btn-generate-transcript');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
    }

    globalInlineMode = true;
    showLoading('Creating podcast script...', 'transcript');

    if (currentEventSource) {
        currentEventSource.close();
    }

    const statusEl = document.getElementById('progress-status-text');
    const barEl = document.getElementById('inline-progress-bar');
    let fullText = '';

    const fileId = window.CURRENT_FILE_ID;
    currentEventSource = new EventSource(`/transcript_stream/${fileId}`);

    currentEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.type === 'token') {
            fullText += data.content;
            if (barEl && fullText.length > 50) {
                const progress = Math.min(10 + (fullText.length / 10), 90);
                barEl.style.width = progress + '%';
            }
            if (statusEl) {
                statusEl.textContent = `Generating script... ${fullText.length} chars`;
            }
        } else if (data.type === 'complete') {
            currentEventSource.close();
            currentEventSource = null;
            if (barEl) {
                barEl.className = 'progress-bar success';
                barEl.style.width = '100%';
            }
            if (statusEl) statusEl.textContent = 'Complete! Loading...';
            setTimeout(() => window.location.reload(), 1000);
        } else if (data.type === 'error') {
            currentEventSource.close();
            currentEventSource = null;
            isGenerating = false;
            resetGenerateButton('transcript');
            showInlineError('transcript', data.error);
        }
    };

    currentEventSource.onerror = function() {
        currentEventSource.close();
        currentEventSource = null;
        isGenerating = false;
        resetGenerateButton('transcript');
        showInlineError('transcript', 'Connection error');
    };
}

function generateSummary() {
    streamSummary();
}

function generatePodcast() {
    if (isGenerating) return;
    isGenerating = true;

    const btn = document.getElementById('btn-generate-audio');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
    }

    globalInlineMode = true;
    showLoading('Generating podcast audio...', 'podcast');

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    const fileId = window.CURRENT_FILE_ID;
    fetch(`/generate_podcast/${fileId}`, {
        method: 'POST',
        signal: controller.signal
    })
    .then(r => {
        clearTimeout(timeoutId);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(data => pollTask(data.task_id, 'podcast', true))
    .catch(err => {
        clearTimeout(timeoutId);
        console.error('Generate podcast error:', err);
        isGenerating = false;
        resetGenerateButton('podcast');
        alert('Error: ' + err.message);
    });
}

function regenerateSummary() {
    if (!confirm('Regenerate summary?')) return;
    streamSummary();
}

function regenerateTranscript() {
    if (!confirm('Regenerate podcast script?')) return;
    streamTranscript();
}

function showWorkflowSteps() {
    const workflowSteps = document.getElementById('workflow-steps-container');
    if (workflowSteps) workflowSteps.style.display = 'block';
}

window.toggleSidebar = function() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');
    sidebar?.classList.toggle('collapsed');
    mainContent?.classList.toggle('sidebar-collapsed');
};

// Expose to window
window.generateSummary = generateSummary;
window.generatePodcast = generatePodcast;
window.streamTranscript = streamTranscript;
window.regenerateSummary = regenerateSummary;
window.regenerateTranscript = regenerateTranscript;
window.pollTask = pollTask;
window.showProgressModal = showProgressModal;
window.showProgressSuccess = showProgressSuccess;
window.showProgressError = showProgressError;
window.hideProgressModal = hideProgressModal;
window.updateProgress = updateProgress;

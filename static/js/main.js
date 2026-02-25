// main.js - Main initialization and event binding

if (typeof pdfjsLib !== 'undefined') {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js';
}

// Global state
window.currentFileId = null;
window.chatHistory = [];

// Expose modal and other utility functions to window
window.showSummary = function() {
    const el = document.getElementById('summary-text');
    if (el && typeof marked !== 'undefined') {
        el.innerHTML = marked.parse(el.textContent || el.innerText);
    }
    window.showModal('summary-modal');
};

window.showOriginalText = function() {
    const contentEl = document.getElementById('original-text-content');
    contentEl.textContent = 'Loading...';
    
    const fileId = window.CURRENT_FILE_ID;
    if (!fileId) {
        contentEl.textContent = 'No file selected';
        return;
    }
    
    fetch(`/file_text/${fileId}`)
        .then(r => r.json())
        .then(data => {
            if (data.text) {
                contentEl.textContent = data.text;
            } else {
                contentEl.innerHTML = '<p class="text-muted">Original text is not available for this file.</p>';
            }
        })
        .catch(err => {
            contentEl.textContent = 'Error loading text: ' + err.message;
        });
    
    window.showModal('original-text-modal');
};

window.showTranscript = function() {
    window.showModal('transcript-modal');
};

window.saveAndGenerate = function() {
    const transcript = document.getElementById('transcript-edit').value;
    const fileId = window.CURRENT_FILE_ID;
    fetch(`/save_transcript/${fileId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ transcript: transcript })
    })
    .then(r => r.json())
    .then(data => {
        window.closeModal('transcript-modal');
        window.generatePodcast();
    })
        .catch(err => {
            showToast('Error saving transcript: ' + err, 'error');
        });
};

window.closeModal = window.closeModal;
window.openChat = window.openChat;
window.sendChat = window.sendChat;

window.deleteFile = function(fileId) {
    if (!confirm('Delete this paper? This will remove the summary, transcript, and any generated audio.')) return;
    
    fetch(`/delete_file/${fileId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showToast('Error: ' + data.error, 'error');
            } else {
                window.location.href = '/';
            }
        })
        .catch(err => showToast('Error: ' + err, 'error'));
};

// Auto-generate initialization (from index.html inline script)
function initAutoGenerate() {
    const urlParams = new URLSearchParams(window.location.search);
    const autoGenerate = urlParams.get('generate');
    const hasSummary = document.body.dataset.hasSummary === 'true';

    if (autoGenerate === 'summary' && !hasSummary) {
        window.globalInlineMode = true;
        const url = new URL(window.location);
        url.searchParams.delete('generate');
        url.searchParams.delete('inline');
        window.history.replaceState({}, '', url.toString());
        setTimeout(() => window.streamSummary(), 500);
    } else if (hasSummary && autoGenerate) {
        const url = new URL(window.location);
        url.searchParams.delete('generate');
        url.searchParams.delete('inline');
        window.history.replaceState({}, '', url.toString());
    }
}

// Page-specific initializations
function initRagflowDatasets() {
    const url = window.ragflowDatasetsUrl || '/ragflow/datasets';
    fetch(url)
        .then(r => r.json())
        .then(data => {
            const select = document.getElementById('ragflow-dataset-select');
            if (select && data.datasets) {
                select.innerHTML = '<option value="">Select a dataset...</option>' +
                    data.datasets.map(d =>
                        `<option value="${d.id}">${d.name}</option>`
                    ).join('');
            }
        });
}

function initFileUpload() {
    const fileInput = document.getElementById('file-input');
    const uploadForm = document.getElementById('upload-form');
    const dropzone = document.getElementById('dropzone');
    const uploadProgress = document.getElementById('upload-progress');
    
    let xhr = null;

    // Drag and drop handlers
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
        
        dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
        
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files.length > 0 && files[0].type === 'application/pdf') {
                handleFileSelect(files[0]);
            } else if (files.length > 0) {
                showToast('Please select a PDF file', 'error');
            }
        });
        
        // Click to browse
        dropzone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON') {
                fileInput?.click();
            }
        });
    }
    
    function handleFileSelect(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showToast('Only PDF files are supported', 'error');
            return;
        }
        
        // Update UI
        document.getElementById('upload-filename').textContent = file.name;
        uploadProgress.style.display = 'block';
        
        // Create FormData
        const formData = new FormData();
        formData.append('file', file);
        
        const ragflowDataset = document.getElementById('ragflow-dataset-select')?.value;
        if (ragflowDataset) {
            formData.append('ragflow_dataset', ragflowDataset);
        }
        
        // Create XHR for progress
        xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                document.getElementById('upload-percentage').textContent = percent + '%';
                document.getElementById('upload-progress-fill').style.width = percent + '%';
            }
        });
        
        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (data.error) {
                        showToast('Upload failed: ' + data.error, 'error');
                        resetUpload();
                    } else {
                        window.location.href = data.redirect || '/?file=' + data.file_id;
                    }
                } catch {
                    window.location.href = '/';
                }
            } else {
                showToast('Upload failed. Please try again.', 'error');
                resetUpload();
            }
        });
        
        xhr.addEventListener('error', () => {
            showToast('Upload failed. Please check your connection.', 'error');
            resetUpload();
        });
        
        xhr.open('POST', uploadForm.action);
        xhr.send(formData);
    }
    
    function resetUpload() {
        uploadProgress.style.display = 'none';
        document.getElementById('upload-percentage').textContent = '0%';
        document.getElementById('upload-progress-fill').style.width = '0%';
    }
    
    window.cancelUpload = function() {
        if (xhr) {
            xhr.abort();
            showToast('Upload cancelled', 'info');
            resetUpload();
        }
    };
    
    // Expose for button click
    window.handleFileSelect = handleFileSelect;
    
    fileInput?.addEventListener('change', function() {
        if (this.files.length > 0) {
            handleFileSelect(this.files[0]);
        }
    });
    
    uploadForm?.addEventListener('submit', function(e) {
        const fileInput = document.getElementById('file-input');
        if (!fileInput || !fileInput.files.length) {
            e.preventDefault();
            showToast('Please select a PDF file to upload.', 'error');
            return;
        }
        
        const file = fileInput.files[0];
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            e.preventDefault();
            showToast('Only PDF files are supported.', 'error');
            return;
        }
    });
}

function initMobileLibrary() {
    if (window.innerWidth <= 768) {
        document.querySelectorAll('.library-sidebar').forEach(sidebar => {
            sidebar.classList.remove('visible');
            sidebar.classList.add('collapsed');
        });
    }
}

// Main initialization
document.addEventListener('DOMContentLoaded', () => {
    // Resume any pending generation tasks
    window.resumePendingTasks();
    
    // Initialize PDF controls
    window.initPdfControls();
    
    // Initialize file list click handlers
    window.initFileListHandlers();
    
    // Initialize chat
    window.initChat();
    
    // Initialize task status
    window.initTaskStatus();
    
    // Sidebar toggle
    document.getElementById('sidebar-toggle')?.addEventListener('click', window.toggleSidebar);
    
    // Settings page
    if (document.querySelector('body.settings-page')) {
        window.initSettingsPage();
    }
    
    // Pre-load chat datasets
    if (document.getElementById('chat-modal')) {
        window.loadRagflowDatasetsForChat();
    }
    
    // Initialize index page specific features
    if (document.getElementById('file-input')) {
        initFileUpload();
    }
    if (document.getElementById('ragflow-dataset-select')) {
        initRagflowDatasets();
    }
    if (window.innerWidth <= 768) {
        initMobileLibrary();
    }
    
    // Auto-generate if requested
    initAutoGenerate();
});

// Expose init functions to window for template use
window.initRagflowDatasets = initRagflowDatasets;
window.initFileUpload = initFileUpload;
window.initMobileLibrary = initMobileLibrary;
window.initAutoGenerate = initAutoGenerate;

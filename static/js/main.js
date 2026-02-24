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
        alert('Error saving transcript: ' + err);
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
                alert('Error: ' + data.error);
            } else {
                window.location.href = '/';
            }
        })
        .catch(err => alert('Error: ' + err));
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
    fetch('{{ url_for("ragflow.ragflow_datasets") }}')
        .then(r => r.json())
        .then(data => {
            const select = document.getElementById('ragflow-dataset-select');
            if (select && data.datasets) {
                select.innerHTML = data.datasets.map(d =>
                    `<option value="${d.id}">${d.name}</option>`
                ).join('');
            }
        });
    
    document.getElementById('upload_to_ragflow')?.addEventListener('change', function() {
        const select = document.getElementById('ragflow-dataset-select');
        if (select) select.style.display = this.checked ? 'block' : 'none';
    });
}

function initFileUpload() {
    const fileInput = document.getElementById('file-input');
    const uploadForm = document.getElementById('upload-form');
    
    fileInput?.addEventListener('change', function() {
        if (this.files.length > 0) {
            const btn = fileInput.nextElementSibling;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Uploading...';
            btn.disabled = true;
            uploadForm.submit();
        }
    });
    
    uploadForm?.addEventListener('submit', function(e) {
        const fileInput = document.getElementById('file-input');
        if (!fileInput || !fileInput.files.length) {
            e.preventDefault();
            alert('Please select a PDF file to upload.');
            return;
        }
        
        const file = fileInput.files[0];
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            e.preventDefault();
            alert('Only PDF files are supported.');
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

// file-manager.js - File and folder management

function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file? This action cannot be undone.')) {
        return;
    }
    fetch(`/delete_file/${fileId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById(`file-item-${fileId}`)?.remove();
                showToast('File deleted successfully', 'success');
            } else {
                showToast('Error deleting file: ' + data.error, 'error');
            }
        })
        .catch(err => showToast('An error occurred: ' + err.message, 'error'));
}

function renameFile(fileId, oldFilename) {
    const newFilename = prompt('Enter new filename:', oldFilename);
    if (newFilename && newFilename !== oldFilename) {
        fetch(`/rename_file/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_filename: newFilename })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const fileItemElement = document.getElementById(`file-item-${fileId}`);
                if (fileItemElement) {
                    const span = fileItemElement.querySelector('span.file-filename');
                    if (span) span.textContent = data.new_filename;

                    const viewDiv = fileItemElement.querySelector('.file-item');
                    if (viewDiv) {
                        viewDiv.dataset.filename = data.new_filename;
                        viewDiv.dataset.url = data.new_url;
                    }

                    const renameButton = fileItemElement.querySelector('[data-action="renameFile"]');
                    if (renameButton) {
                        renameButton.dataset.filename = data.new_filename;
                    }
                }
                showToast('File renamed successfully', 'success');
            } else {
                showToast('Error renaming file: ' + data.error, 'error');
            }
        })
        .catch(err => showToast('An error occurred: ' + err.message, 'error'));
    }
}

function moveFile(fileId) {
    const folderId = prompt('Enter the ID of the folder to move this file to (or "root" for no folder):');
    if (folderId) {
        fetch(`/move_file/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_folder_id: folderId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const fileElement = document.getElementById(`file-item-${fileId}`);
                if (fileElement) {
                    const targetListId = (folderId === 'root') ? 'root-file-list' : `folder-list-${folderId}`;
                    const targetList = document.getElementById(targetListId);
                    if (targetList) {
                        targetList.appendChild(fileElement);
                        showToast('File moved successfully', 'success');
                    } else {
                        showToast('Target folder not found in the UI', 'error');
                    }
                }
            } else {
                showToast('Error moving file: ' + data.error, 'error');
            }
        })
        .catch(err => showToast('An error occurred: ' + err.message, 'error'));
    }
}

function deleteFolder(folderId) {
    if (!confirm('Are you sure you want to delete this folder? It must be empty.')) {
        return;
    }
    fetch(`/delete_folder/${folderId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById(`folder-item-${folderId}`)?.remove();
                showToast('Folder deleted successfully', 'success');
            } else {
                showToast('Error deleting folder: ' + data.error, 'error');
            }
        })
        .catch(err => showToast('An error occurred: ' + err.message, 'error'));
}

function renameFolder(folderId, oldName) {
    const newName = prompt('Enter new folder name:', oldName);
    if (newName && newName !== oldName) {
        fetch(`/rename_folder/${folderId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const folderItem = document.getElementById(`folder-item-${folderId}`);
                if (folderItem) {
                    folderItem.querySelector('strong').textContent = data.new_name;
                    const renameButton = folderItem.querySelector('[data-action="renameFolder"]');
                    if (renameButton) {
                        renameButton.dataset.name = newName;
                    }
                }
                showToast('Folder renamed successfully', 'success');
            } else {
                showToast('Error renaming folder: ' + data.error, 'error');
            }
        })
        .catch(err => showToast('An error occurred: ' + err.message, 'error'));
    }
}

function initFileListHandlers() {
    const fileList = document.getElementById('file-list');
    if (!fileList) return;

    fileList.addEventListener('click', (event) => {
        const folderToggle = event.target.closest('.folder-toggle');
        const fileItem = event.target.closest('.file-item');
        const actionButton = event.target.closest('.file-action-button, .folder-action-button');

        if (folderToggle) {
            event.preventDefault();
            const folderContainer = folderToggle.closest('.folder-container');
            const sublist = folderContainer.querySelector('.nav');
            folderToggle.classList.toggle('collapsed');
            new bootstrap.Collapse(sublist, { toggle: true });
        }
        else if (actionButton) {
            event.preventDefault();
            const { action, id, filename, name } = actionButton.dataset;

            switch (action) {
                case 'renameFile':
                    renameFile(id, filename);
                    break;
                case 'moveFile':
                    moveFile(id);
                    break;
                case 'deleteFile':
                    deleteFile(id);
                    break;
                case 'summarizeFile':
                    window.summarizeFile(id);
                    break;
                case 'generateTranscript':
                    window.generateTranscript(id);
                    break;
                case 'generatePodcast':
                    window.generatePodcast(id);
                    break;
                case 'renameFolder':
                    renameFolder(id, name);
                    break;
                case 'deleteFolder':
                    deleteFolder(id);
                    break;
            }
        } else if (fileItem) {
            const { url, id, filename } = fileItem.dataset;
            window.viewPdf(url, id, filename);
        }
    });
}

// Expose to window
window.deleteFile = deleteFile;
window.renameFile = renameFile;
window.moveFile = moveFile;
window.deleteFolder = deleteFolder;
window.renameFolder = renameFolder;
window.initFileListHandlers = initFileListHandlers;

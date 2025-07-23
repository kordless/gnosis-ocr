// Gnosis OCR-S Web Application

// Constants
const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
const MAX_NORMAL_UPLOAD_SIZE = 20 * 1024 * 1024; // 20MB

// Modal Manager
class ModalManager {
    static show(title, content, type = 'info') {
        const modal = document.getElementById('session-modal');
        const modalTitle = document.getElementById('modal-title');
        const modalBody = document.getElementById('modal-body');
        
        modalTitle.textContent = title;
        modalBody.innerHTML = content;
        
        // Add type class for styling
        modal.className = `modal modal-${type}`;
        modal.style.display = 'block';
    }
    
    static showProgress(title, message, progress = 0) {
        const content = `
            <div class="modal-progress">
                <p class="progress-message">${message}</p>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${progress}%"></div>
                </div>
                <p class="progress-percent">${progress}%</p>
            </div>
        `;
        this.show(title, content, 'progress');
    }
    
    static updateProgress(message, progress) {
        const messageEl = document.querySelector('.modal-progress .progress-message');
        const fillEl = document.querySelector('.modal-progress .progress-fill');
        const percentEl = document.querySelector('.modal-progress .progress-percent');
        
        if (messageEl) messageEl.textContent = message;
        if (fillEl) fillEl.style.width = `${progress}%`;
        if (percentEl) percentEl.textContent = `${progress}%`;
    }
    
    static close() {
        document.getElementById('session-modal').style.display = 'none';
    }
    
    static confirm(title, message) {
        return new Promise((resolve) => {
            const content = `
                <div class="modal-confirm">
                    <p>${message}</p>
                    <div class="modal-buttons">
                        <button class="upload-button" onclick="ModalManager._confirmResolve(true)">Yes</button>
                        <button class="cancel-button" onclick="ModalManager._confirmResolve(false)">No</button>
                    </div>
                </div>
            `;
            this.show(title, content, 'confirm');
            ModalManager._confirmResolver = resolve;
        });
    }
    
    static _confirmResolve(value) {
        if (ModalManager._confirmResolver) {
            ModalManager._confirmResolver(value);
            ModalManager._confirmResolver = null;
            ModalManager.close();
        }
    }
}

// Session Manager Class
class SessionManager {
    constructor() {
        this.sessions = this.loadSessions();
        this.progressTracker = new Map(); // Track highest progress for each session
        this.pageTracker = new Map(); // Track highest page count for each session
        this.updateUI();
        // Check status of all sessions on page load
        this.refreshAllSessionStatus();
        // Set up periodic refresh
        this.startPeriodicRefresh();
    }

    startPeriodicRefresh() {
        // Refresh every 10 seconds for active sessions
        setInterval(() => {
            const activeSessions = this.sessions.filter(s => 
                s.status === 'processing' || s.status === 'uploaded'
            );
            if (activeSessions.length > 0) {
                this.refreshAllSessionStatus();
            }
        }, 10000);
    }


    loadSessions() {
        const stored = localStorage.getItem('gnosis_ocr_sessions');
        return stored ? JSON.parse(stored) : [];
    }

    saveSessions() {
        localStorage.setItem('gnosis_ocr_sessions', JSON.stringify(this.sessions));
        this.updateUI();
    }

    addSession(sessionData) {
        this.sessions.unshift(sessionData); // Add to beginning
        this.sessions = this.sessions.slice(0, 50); // Keep last 50
        this.saveSessions();
    }

    updateSession(sessionId, updates) {
        const index = this.sessions.findIndex(s => s.sessionId === sessionId);
        if (index !== -1) {
            this.sessions[index] = { ...this.sessions[index], ...updates };
            this.saveSessions();
        }
    }

    async clearAll() {
        const confirmed = await ModalManager.confirm(
            'Clear All Sessions',
            'Are you sure you want to clear all sessions? This only removes them from your browser history, not from the server.'
        );
        
        if (confirmed) {
            this.sessions = [];
            this.saveSessions();
        }
    }

    async refreshAllSessionStatus() {
        // Check status of all sessions by looking for session_status.json
        for (const session of this.sessions) {
            if (session.status === 'processing' || (session.status === 'uploaded' && session.fileType === 'pdf')) {
                try {
                    // Try to fetch session_status.json
                    const statusUrl = `/storage/${session.userHash}/${session.sessionId}/session_status.json`;
                    const response = await fetch(statusUrl);
                    
                    if (response.ok) {
                        let statusData;
                        try {
                            statusData = await response.json();
                        } catch (jsonError) {
                            // JSON is corrupted, rebuild it
                            console.warn(`Corrupted session_status.json for ${session.sessionId}, rebuilding...`);
                            statusData = await this.rebuildSessionStatus(session.sessionId);
                            if (!statusData) continue; // Skip if rebuild failed
                        }
                        
                        // Process the status data using the helper method
                        await this.processStatusData(session, statusData);
                        
                        // Handle backward compatibility for old single-stage format
                        if (!statusData.stages) {
                            // Old single-stage format - keep backward compatibility
                            const lastProgress = this.progressTracker.get(session.sessionId) || 0;
                            const lastPages = this.pageTracker.get(session.sessionId) || 0;
                            
                            const currentProgress = statusData.progress_percent || 0;
                            const currentPages = statusData.pages_extracted || 0;
                            
                            const safeProgress = Math.max(currentProgress, lastProgress);
                            const safePages = Math.max(currentPages, lastPages);
                            
                            this.progressTracker.set(session.sessionId, safeProgress);
                            this.pageTracker.set(session.sessionId, safePages);
                            
                            if (statusData.status === 'complete' && statusData.pages_extracted > 0) {
                                this.updateSession(session.sessionId, {
                                    status: 'ready_for_ocr',
                                    pageCount: statusData.pages_extracted,
                                    extractionProgress: 100
                                });
                            } else if (statusData.status === 'processing') {
                                this.updateSession(session.sessionId, {
                                    status: 'processing',
                                    extractionProgress: safeProgress,
                                    pageCount: statusData.pages_extracted || 0,
                                    totalPages: statusData.total_pages || 0
                                });
                            }
                        }
                    } else if (response.status === 404 && session.status === 'uploaded' && session.fileType === 'pdf') {
                        // No status file yet, try to rebuild it from actual files
                        console.info(`No session_status.json found for ${session.sessionId}, attempting to rebuild...`);
                        const rebuiltStatus = await this.rebuildSessionStatus(session.sessionId);
                        if (rebuiltStatus) {
                            // Process the rebuilt status data
                            await this.processStatusData(session, rebuiltStatus);
                        } else {
                            // Fallback: PDF is ready for extraction
                            this.updateSession(session.sessionId, {
                                status: 'uploaded',
                                extractionProgress: 0
                            });
                        }
                    }
                } catch (error) {
                    console.error(`Error checking session status for ${session.sessionId}:`, error);
                }
            }
            
            // For any session, also check if session_status.json exists to update status
            // This handles page refresh scenarios where status might have changed
            if (session.fileType === 'pdf' && session.userHash && session.sessionId) {
                try {
                    const statusUrl = `/storage/${session.userHash}/${session.sessionId}/session_status.json`;
                    const response = await fetch(statusUrl);
                    
                    if (response.ok) {
                        const statusData = await response.json();
                        
                        // Handle multi-stage format
                        if (statusData.stages && statusData.stages.page_extraction) {
                            const extractionStage = statusData.stages.page_extraction;
                            
                            if (extractionStage.status === 'complete' && extractionStage.total_pages > 0 && session.status !== 'ready_for_ocr' && session.status !== 'ocr_processing' && session.status !== 'ocr_complete') {
                                // Update session that was marked differently but is actually complete
                                this.updateSession(session.sessionId, {
                                    status: 'ready_for_ocr',
                                    pageCount: extractionStage.total_pages,
                                    extractionProgress: 100
                                });
                            }
                        } else if (statusData.status === 'complete' && statusData.pages_extracted > 0 && session.status !== 'ready_for_ocr') {
                            // Old format - backward compatibility
                            this.updateSession(session.sessionId, {
                                status: 'ready_for_ocr',
                                pageCount: statusData.pages_extracted,
                                extractionProgress: 100
                            });
                        }
                    }
                } catch (error) {
                    // Ignore errors for this secondary check
                }
            }
        }
    }

    async rebuildSessionStatus(sessionId) {
        """Rebuild session status by calling the API endpoint"""
        try {
            const response = await fetch(`/api/jobs/${sessionId}/rebuild-status`, {
                method: 'POST',
                headers: {
                    'X-User-Email': getUserEmail()
                }
            });
            
            if (response.ok) {
                const result = await response.json();
                console.info(`Successfully rebuilt status for session ${sessionId}`);
                return result.data;
            } else {
                console.error(`Failed to rebuild status for session ${sessionId}: ${response.status}`);
                return null;
            }
        } catch (error) {
            console.error(`Error rebuilding status for session ${sessionId}:`, error);
            return null;
        }
    }

    async processStatusData(session, statusData) {
        """Process status data and update session accordingly"""
        // Handle multi-stage format
        if (statusData.stages) {
            const extractionStage = statusData.stages.page_extraction;
            const ocrStage = statusData.stages.ocr;
            
            if (extractionStage) {
                // Get last known progress for extraction
                const lastProgress = this.progressTracker.get(session.sessionId + '_extraction') || 0;
                const lastPages = this.pageTracker.get(session.sessionId + '_extraction') || 0;
                
                const safeProgress = Math.max(extractionStage.progress_percent || 0, lastProgress);
                const safePages = Math.max(extractionStage.pages_processed || 0, lastPages);
                
                this.progressTracker.set(session.sessionId + '_extraction', safeProgress);
                this.pageTracker.set(session.sessionId + '_extraction', safePages);
                
                if (extractionStage.status === 'complete') {
                    // Extraction complete
                    this.updateSession(session.sessionId, {
                        status: 'ready_for_ocr',
                        pageCount: extractionStage.total_pages,
                        extractionProgress: 100
                    });
                } else if (extractionStage.status === 'processing') {
                    // Still extracting
                    this.updateSession(session.sessionId, {
                        status: 'processing',
                        extractionProgress: safeProgress,
                        pageCount: safePages,
                        totalPages: extractionStage.total_pages
                    });
                }
            }
            
            if (ocrStage) {
                // Get last known progress for OCR
                const lastOcrProgress = this.progressTracker.get(session.sessionId + '_ocr') || 0;
                const lastOcrPages = this.pageTracker.get(session.sessionId + '_ocr') || 0;
                
                const safeOcrProgress = Math.max(ocrStage.progress_percent || 0, lastOcrProgress);
                const safeOcrPages = Math.max(ocrStage.pages_processed || 0, lastOcrPages);
                
                this.progressTracker.set(session.sessionId + '_ocr', safeOcrProgress);
                this.pageTracker.set(session.sessionId + '_ocr', safeOcrPages);
                
                if (ocrStage.status === 'complete') {
                    // OCR complete
                    this.updateSession(session.sessionId, {
                        status: 'ocr_complete',
                        ocrProgress: 100,
                        ocrPagesProcessed: ocrStage.pages_processed
                    });
                } else if (ocrStage.status === 'processing') {
                    // OCR in progress
                    this.updateSession(session.sessionId, {
                        status: 'ocr_processing',
                        ocrProgress: safeOcrProgress,
                        ocrPagesProcessed: safeOcrPages,
                        ocrTotalPages: ocrStage.total_pages
                    });
                }
            }
        }
    }

    updateUI() {
        const listEl = document.getElementById('session-list');
        const emptyEl = document.getElementById('empty-state');
        const countEl = document.getElementById('session-count');

        countEl.textContent = `${this.sessions.length} session${this.sessions.length !== 1 ? 's' : ''}`;

        if (this.sessions.length === 0) {
            listEl.style.display = 'none';
            emptyEl.style.display = 'block';
            return;
        }

        listEl.style.display = 'grid';
        emptyEl.style.display = 'none';


        listEl.innerHTML = this.sessions.map(session => {
            let actionButton = '';
            
            if (session.status === 'uploaded' && session.fileType === 'pdf') {
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); startExtractPages('${session.sessionId}')">Extract Images</button>`;
            } else if (session.status === 'uploaded' && session.fileType === 'image') {
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); startOCR('${session.sessionId}')">Start OCR</button>`;
            } else if (session.status === 'ready_for_ocr') {
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); startOCR('${session.sessionId}')">Start OCR</button>`;
            } else if (session.status === 'processing') {
                const progress = session.extractionProgress || 0;
                actionButton = `<span class="session-status status-processing">Extracting ${progress}% <div class="spinner-small"></div></span>`;
            } else if (session.status === 'ocr_processing') {
                const progress = session.ocrProgress || 0;
                actionButton = `<span class="session-status status-processing">OCR ${progress}% <div class="spinner-small"></div></span>`;
            } else if (session.status === 'ocr_complete') {
                actionButton = `<span class="session-status status-complete">OCR Complete</span>`;
            } else {
                actionButton = `<span class="session-status status-${session.status}">${session.status}</span>`;
            }
            
            return `
                <div class="session-item" onclick="viewSession('${session.sessionId}')">
                    <div class="session-info">
                        <div class="session-filename">${escapeHtml(session.filename)}</div>
                        <div class="session-meta">
                            ${new Date(session.uploadedAt).toLocaleString()} • 
                            ${formatFileSize(session.fileSize)} • 
                            ${session.fileType || 'unknown'}
                            ${session.pageCount ? ` • ${session.pageCount} pages` : ''}
                        </div>
                    </div>
                    ${actionButton}
                </div>
            `;

        }).join('');

    }
}

// File Upload Handler
class FileUploader {
    constructor() {
        this.setupEventListeners();
        this.chunkSize = CHUNK_SIZE;
    }

    getFileType(filename) {
        const ext = filename.toLowerCase().split('.').pop();
        if (ext === 'pdf') return 'pdf';
        if (['png', 'jpg', 'jpeg', 'webp', 'tiff'].includes(ext)) return 'image';
        return 'unknown';
    }

    setupEventListeners() {
        const uploadArea = document.getElementById('upload-area');
        const fileInput = document.getElementById('file-input');


        // Drag and drop
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('drag-over');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('drag-over');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) this.handleFile(file);
        });

        // File input
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) this.handleFile(file);
        });
    }

    async handleFile(file) {
        // Validate file type
        const validExtensions = ['.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tiff'];
        const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
        
        if (!validExtensions.includes(fileExtension)) {
            ModalManager.show(
                'Invalid File Type',
                'Please upload a PDF or image file (PDF, PNG, JPG, JPEG, WebP, TIFF)',
                'error'
            );
            return;
        }

        // Show progress
        const progressEl = document.getElementById('upload-progress');
        const progressFill = document.getElementById('progress-fill');
        const progressText = document.getElementById('progress-text');
        progressEl.style.display = 'block';

        try {
            // Check if force chunking is enabled
            const forceChunking = document.getElementById('force-chunking').checked;
            
            // Determine upload method
            const useChunking = forceChunking || file.size > MAX_NORMAL_UPLOAD_SIZE;
            
            if (useChunking) {
                await this.chunkedUpload(file, progressFill, progressText);
            } else {
                await this.normalUpload(file, progressFill, progressText);
            }
        } catch (error) {
            console.error('Upload error:', error);
            ModalManager.show('Upload Failed', error.message, 'error');
        } finally {
            // Reset UI
            setTimeout(() => {
                progressEl.style.display = 'none';
                progressFill.style.width = '0%';
                document.getElementById('file-input').value = '';
            }, 1000);
        }
    }

    async normalUpload(file, progressFill, progressText) {
        progressText.textContent = 'Uploading...';
        
        // Simulate progress for normal upload
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += 10;
            if (progress < 90) {
                progressFill.style.width = progress + '%';
            }
        }, 100);

        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/storage/upload', {
            method: 'POST',
            body: formData,
            headers: {
                'X-User-Email': getUserEmail()
            }
        });

        clearInterval(progressInterval);

        if (!response.ok) {
            const error = await response.text();
            throw new Error(error || 'Upload failed');
        }

        const data = await response.json();
        progressFill.style.width = '100%';
        progressText.textContent = 'Upload complete!';

        // Add to sessions
        sessionManager.addSession({
            sessionId: data.session_id,
            filename: file.name,
            fileSize: file.size,
            fileType: this.getFileType(file.name),
            uploadedAt: new Date().toISOString(),
            status: 'uploaded',
            userHash: await computeUserHash(getUserEmail()),
            uploadMethod: 'normal'
        });


        // View the session after a short delay
        setTimeout(() => {
            viewSession(data.session_id);
        }, 500);
    }

    async chunkedUpload(file, progressFill, progressText) {
        const totalChunks = Math.ceil(file.size / this.chunkSize);
        
        // Start chunked upload with retry logic
        progressText.textContent = 'Initializing chunked upload...';
        
        let startResponse;
        let initAttempts = 0;
        const maxInitAttempts = 3;
        const retryDelay = 3500; // 3.5 seconds between attempts
        
        while (initAttempts < maxInitAttempts) {
            try {
                startResponse = await fetch('/storage/upload', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-User-Email': getUserEmail()
                    },
                    body: JSON.stringify({
                        filename: file.name,
                        total_size: file.size,
                        total_chunks: totalChunks
                    })
                });

                if (!startResponse.ok) {
                    const errorText = await startResponse.text();
                    
                    // Check if we got HTML back and retry if we haven't exhausted attempts
                    if (errorText.includes('<!DOCTYPE html>') && initAttempts < maxInitAttempts - 1) {
                        initAttempts++;
                        console.log(`Upload initialization attempt ${initAttempts} failed (got HTML). Retrying in ${retryDelay/1000} seconds...`);
                        progressText.textContent = `Initializing upload - Retry ${initAttempts}/${maxInitAttempts}...`;
                        await new Promise(resolve => setTimeout(resolve, retryDelay));
                        continue;
                    } else if (errorText.includes('<!DOCTYPE html>')) {
                        throw new Error(`Failed to start upload after ${initAttempts + 1} attempts: Server returned HTML. The endpoint may not be deployed yet.`);
                    }
                    
                    throw new Error(errorText || 'Failed to start upload');
                }
                
                // Success - break out of retry loop
                break;
                
            } catch (fetchError) {
                // Network error or other fetch failure
                if (initAttempts < maxInitAttempts - 1) {
                    initAttempts++;
                    console.log(`Upload initialization attempt ${initAttempts} failed (${fetchError.message}). Retrying...`);
                    progressText.textContent = `Network error - Retry ${initAttempts}/${maxInitAttempts}...`;
                    await new Promise(resolve => setTimeout(resolve, retryDelay));
                    continue;
                }
                throw fetchError;
            }
        }

        const { session_id } = await startResponse.json();

        // Upload chunks
        for (let i = 0; i < totalChunks; i++) {
            const start = i * this.chunkSize;
            const end = Math.min(start + this.chunkSize, file.size);
            const chunk = file.slice(start, end);

            const formData = new FormData();
            formData.append('file', chunk);

            // Retry logic for chunk upload - sometimes endpoints take a moment to warm up
            let chunkResponse;
            let uploadAttempts = 0;
            const maxUploadAttempts = 3;
            const retryDelay = 3500; // 3.5 seconds between attempts
            
            while (uploadAttempts < maxUploadAttempts) {
                try {
                    chunkResponse = await fetch(`/storage/upload/${session_id}/chunk`, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-User-Email': getUserEmail(),
                            'X-Chunk-Number': i.toString()
                        }
                    });

                    if (!chunkResponse.ok) {
                        const errorText = await chunkResponse.text();
                        
                        // Check if we got HTML back (indicating a 404 or other routing issue)
                        if (errorText.includes('<!DOCTYPE html>') && uploadAttempts < maxUploadAttempts - 1) {
                            uploadAttempts++;
                            console.log(`Chunk ${i + 1} upload attempt ${uploadAttempts} failed (got HTML). Retrying in ${retryDelay/1000} seconds...`);
                            progressText.textContent = `Chunk ${i + 1} - Retry attempt ${uploadAttempts}/${maxUploadAttempts}...`;
                            await new Promise(resolve => setTimeout(resolve, retryDelay));
                            continue;
                        } else if (errorText.includes('<!DOCTYPE html>')) {
                            throw new Error(`Chunk ${i + 1} failed after ${uploadAttempts + 1} attempts: Server returned HTML instead of API response. The endpoint may not be deployed yet.`);
                        }
                        
                        throw new Error(`Chunk ${i + 1} failed: ${errorText}`);
                    }
                    
                    // Success - break out of retry loop
                    break;
                    
                } catch (fetchError) {
                    // Network error or other fetch failure
                    if (uploadAttempts < maxUploadAttempts - 1) {
                        uploadAttempts++;
                        console.log(`Chunk ${i + 1} upload attempt ${uploadAttempts} failed (${fetchError.message}). Retrying...`);
                        progressText.textContent = `Chunk ${i + 1} - Network error, retrying ${uploadAttempts}/${maxUploadAttempts}...`;
                        await new Promise(resolve => setTimeout(resolve, retryDelay));
                        continue;
                    }
                    throw fetchError;
                }
            }

            const progress = ((i + 1) / totalChunks) * 100;
            progressFill.style.width = progress + '%';
            progressText.textContent = `Uploading chunks... ${i + 1}/${totalChunks} (${Math.round(progress)}%)`;
        }

        progressText.textContent = 'All chunks uploaded! Assembling file...';

        // Call the assemble endpoint
        let assembleAttempts = 0;
        const maxAssembleAttempts = 3;
        
        while (assembleAttempts < maxAssembleAttempts) {
            try {
                const assembleResponse = await fetch(`/storage/upload/${session_id}/assemble`, {
                    method: 'POST',
                    headers: {
                        'X-User-Email': getUserEmail()
                    }
                });
                
                if (!assembleResponse.ok) {
                    throw new Error(`Assembly failed: ${await assembleResponse.text()}`);
                }
                
                const assembleResult = await assembleResponse.json();
                
                if (assembleResult.status === 'complete') {
                    // Assembly successful
                    progressText.textContent = 'File assembled successfully! Verifying...';
                    
                    // For large files, assembly might take time. Poll for file availability.
                    const userHash = await computeUserHash(getUserEmail());
                    let fileReady = false;
                    let verifyAttempts = 0;
                    const maxVerifyAttempts = 30; // 30 attempts * 5 seconds = 2.5 minutes max wait
                    
                    while (!fileReady && verifyAttempts < maxVerifyAttempts) {
                        try {
                            const fileCheckResponse = await fetch(
                                `/storage/${userHash}/${session_id}/${file.name}`,
                                { method: 'HEAD' }
                            );
                            
                            if (fileCheckResponse.ok) {
                                fileReady = true;
                                progressText.textContent = 'Upload completed successfully!';
                                
                                // Add to sessions
                                sessionManager.addSession({
                                    sessionId: session_id,
                                    filename: file.name,
                                    fileSize: file.size,
                                    fileType: this.getFileType(file.name),
                                    uploadedAt: new Date().toISOString(),
                                    status: 'uploaded',
                                    userHash: userHash,
                                    uploadMethod: 'chunked'
                                });
                                
                                // View the session after a short delay
                                setTimeout(() => {
                                    viewSession(session_id);
                                }, 500);
                                
                                return; // Success, exit the function
                            } else if (fileCheckResponse.status === 500) {
                                // Server error - file might still be processing
                                verifyAttempts++;
                                if (verifyAttempts < maxVerifyAttempts) {
                                    progressText.textContent = `Waiting for file to be ready... (${verifyAttempts * 5}s)`;
                                    await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5 seconds
                                } else {
                                    throw new Error('File verification timed out - the file is very large and may still be processing. Please check back in a few minutes.');
                                }
                            } else {
                                throw new Error(`File verification failed with status ${fileCheckResponse.status}`);
                            }
                        } catch (error) {
                            if (error.message.includes('timed out')) {
                                throw error;
                            }
                            // Network error - retry
                            verifyAttempts++;
                            if (verifyAttempts < maxVerifyAttempts) {
                                progressText.textContent = `Network error, retrying... (${verifyAttempts}/${maxVerifyAttempts})`;
                                await new Promise(resolve => setTimeout(resolve, 5000));
                            } else {
                                throw new Error('File verification failed after multiple attempts');
                            }
                        }
                    }
                    
                } else if (assembleResult.status === 'incomplete') {
                    // Missing chunks - attempt to re-upload them
                    const missingChunks = assembleResult.missing_chunks;
                    progressText.textContent = `Missing ${missingChunks.length} chunks. Re-uploading...`;
                    
                    // Re-upload missing chunks
                    for (let i = 0; i < missingChunks.length; i++) {
                        const chunkNum = missingChunks[i];
                        const start = chunkNum * this.chunkSize;
                        const end = Math.min(start + this.chunkSize, file.size);
                        const chunk = file.slice(start, end);

                        const formData = new FormData();
                        formData.append('file', chunk);

                        const retryResponse = await fetch(`/storage/upload/${session_id}/chunk`, {
                            method: 'POST',
                            body: formData,
                            headers: {
                                'X-User-Email': getUserEmail(),
                                'X-Chunk-Number': chunkNum.toString()
                            }
                        });

                        if (!retryResponse.ok) {
                            throw new Error(`Failed to re-upload chunk ${chunkNum}`);
                        }
                        
                        // Update progress
                        progressText.textContent = `Re-uploading missing chunks... ${i + 1}/${missingChunks.length}`;
                    }
                    
                    // Increment attempt counter and try assembly again
                    assembleAttempts++;
                    progressText.textContent = 'Retrying assembly...';
                    
                    // Small delay before retry
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    continue; // Try assembly again
                }
                
            } catch (error) {
                console.error('Upload assembly failed:', error);
                ModalManager.show(
                    'Upload Failed',
                    `Failed to assemble the uploaded file: ${error.message}. Please try uploading again.`,
                    'error'
                );
                return;
            }
        }
        
        // If we get here, max attempts exceeded
        ModalManager.show(
            'Upload Failed',
            'Failed to assemble file after multiple attempts. Please try uploading again.',
            'error'
        );



        // View the session after a short delay
        setTimeout(() => {
            viewSession(session_id);
        }, 500);
    }
}

// Job Progress Monitor
class JobProgressMonitor {
    constructor() {
        this.activeJobs = new Map();
    }
    
    async startMonitoring(sessionId, jobId) {
        // Start polling job status
        const pollInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/jobs/${sessionId}/${jobId}`, {
                    headers: {
                        'X-User-Email': getUserEmail()
                    }
                });
                
                if (!response.ok) {
                    throw new Error('Failed to get job status');
                }
                
                const job = await response.json();
                
                // Update progress modal
                if (job.progress) {
                    const message = job.progress.message || 'Processing...';
                    const percent = job.progress.percent || 0;
                    ModalManager.updateProgress(message, percent);
                }
                
                // Check if job is complete
                if (job.status === 'completed') {
                    clearInterval(pollInterval);
                    this.activeJobs.delete(jobId);
                    
                    // Check if this is a continuation job (not the final one)
                    // Look for the continuation message in the job's status update
                    const hasMorePages = job.progress && job.progress.current < job.progress.total;
                    const isContinuation = hasMorePages || (job.progress?.message || '').includes('Continuation job created');

                    
                    if (isContinuation) {
                        // Don't show completion for intermediate jobs
                        // Just keep the progress modal updated
                        ModalManager.updateProgress(job.progress.message, 100);
                        
                        // Check for new jobs after a short delay
                        setTimeout(async () => {
                            try {
                                // Get all jobs for this session
                                const jobsResponse = await fetch(`/api/jobs/${sessionId}`, {
                                    headers: {
                                        'X-User-Email': getUserEmail()
                                    }
                                });
                                
                                if (jobsResponse.ok) {
                                    const jobsData = await jobsResponse.json();
                                    // Find the newest queued or processing job
                                    const nextJob = jobsData.jobs.find(j => 
                                        j.status === 'queued' || j.status === 'processing'
                                    );
                                    
                                    if (nextJob) {
                                        // Start monitoring the continuation job
                                        jobMonitor.startMonitoring(sessionId, nextJob.job_id);
                                    }
                                }
                            } catch (error) {
                                console.error('Error checking for continuation jobs:', error);
                            }
                        }, 6000); // Wait 6 seconds (longer than poll interval) for the continuation job to be created

                    } else {

                        // This is the final job - show completion
                        sessionManager.updateSession(sessionId, { 
                            status: 'ready_for_ocr',
                            pageCount: job.output?.page_count || 0
                        });
                        
                        // Force UI refresh to show updated page count
                        sessionManager.updateUI();
                        
                        ModalManager.show(
                            'Extraction Complete',
                            `Successfully extracted ${job.output?.page_count || 0} pages from the PDF.`,
                            'success'
                        );
                    }

                } else if (job.status === 'failed') {
                    clearInterval(pollInterval);
                    this.activeJobs.delete(jobId);
                    
                    sessionManager.updateSession(sessionId, { status: 'uploaded' });
                    
                    ModalManager.show(
                        'Extraction Failed',
                        job.error || 'An error occurred during processing.',
                        'error'
                    );
                }
            } catch (error) {
                console.error('Error polling job status:', error);
            }
        }, 5000); // Poll every 5 seconds

        
        this.activeJobs.set(jobId, pollInterval);
    }
    
    stopMonitoring(jobId) {
        const interval = this.activeJobs.get(jobId);
        if (interval) {
            clearInterval(interval);
            this.activeJobs.delete(jobId);
        }
    }
}

// Helper Functions
function getUserEmail() {
    // In a real app, this would come from auth
    return localStorage.getItem('user_email') || 'anonymous@gnosis-ocr.local';
}

async function computeUserHash(email) {
    // Use Web Crypto API for proper hashing
    const encoder = new TextEncoder();
    const data = encoder.encode(email);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return hashHex.substring(0, 12);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function viewSession(sessionId) {
    const session = sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) {
        ModalManager.show('Session Not Found', 'Session not found in local history', 'error');
        return;
    }

    const content = `
        <div class="session-details">
            <p><strong>Session ID:</strong> ${session.sessionId}</p>
            <p><strong>Uploaded:</strong> ${new Date(session.uploadedAt).toLocaleString()}</p>
            <p><strong>Size:</strong> ${formatFileSize(session.fileSize)}</p>
            <p><strong>Upload Method:</strong> ${session.uploadMethod || 'normal'}</p>
            <p><strong>Status:</strong> <span class="session-status status-${session.status}">${session.status}</span></p>
            ${session.pageCount ? `<p><strong>Pages:</strong> ${session.pageCount}</p>` : ''}
            
            <a href="/storage/${session.userHash}/${session.sessionId}/${session.filename}" 
               target="_blank" 
               class="upload-button file-link">
                View File
            </a>
        </div>
    `;

    ModalManager.show(session.filename, content);
}

function closeModal() {
    ModalManager.close();
}

function clearAllSessions() {
    sessionManager.clearAll();
}

// Initialize everything when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize managers
    window.sessionManager = new SessionManager();
    window.uploader = new FileUploader();
    window.jobMonitor = new JobProgressMonitor();
    window.ModalManager = ModalManager;
    
    // Update user email display
    document.getElementById('user-email').textContent = getUserEmail();
    
    // Set up modal close handler
    window.onclick = function(event) {
        const modal = document.getElementById('session-modal');
        if (event.target === modal) {
            closeModal();
        }
    };
    
    // Set up keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModal();
        }
    });
});

// Job management functions
async function startExtractPages(sessionId) {
    const session = sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) return;
    
    // Update session status to processing
    sessionManager.updateSession(sessionId, { status: 'processing', extractionProgress: 0 });
    
    // Show progress modal
    ModalManager.showProgress('Extracting Images', 'Starting extraction...', 0);
    
    try {
        // Create extraction job
        const response = await fetch('/api/jobs/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Email': getUserEmail()
            },
            body: JSON.stringify({
                session_id: sessionId,
                job_type: 'extract_pages',
                input_data: {
                    filename: session.filename
                }
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to create extraction job');
        }
        
        const job = await response.json();
        
        // Start monitoring the extraction progress via session_status.json
        const monitorInterval = setInterval(async () => {
            try {
                const statusUrl = `/storage/${session.userHash}/${sessionId}/session_status.json`;
                const statusResponse = await fetch(statusUrl);
                
                if (statusResponse.ok) {
                    const statusData = await statusResponse.json();
                    
                    // Handle multi-stage format
                    if (statusData.stages && statusData.stages.page_extraction) {
                        const extractionStage = statusData.stages.page_extraction;
                        
                        // Get last known progress and pages
                        const lastProgress = sessionManager.progressTracker.get(sessionId + '_extraction') || 0;
                        const lastPages = sessionManager.pageTracker.get(sessionId + '_extraction') || 0;
                        
                        const safeProgress = Math.max(extractionStage.progress_percent || 0, lastProgress);
                        const safePages = Math.max(extractionStage.pages_processed || 0, lastPages);
                        
                        sessionManager.progressTracker.set(sessionId + '_extraction', safeProgress);
                        sessionManager.pageTracker.set(sessionId + '_extraction', safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Extracting page ${safePages} of ${extractionStage.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (extractionStage.status === 'complete') {
                            clearInterval(monitorInterval);
                            sessionManager.updateSession(sessionId, {
                                status: 'ready_for_ocr',
                                pageCount: extractionStage.total_pages,
                                extractionProgress: 100
                            });
                            
                            ModalManager.show(
                                'Extraction Complete',
                                `Successfully extracted ${extractionStage.total_pages} images from the PDF.`,
                                'success'
                            );
                        }
                    } else {
                        // Fall back to old format for backward compatibility
                        const lastProgress = sessionManager.progressTracker.get(sessionId) || 0;
                        const lastPages = sessionManager.pageTracker.get(sessionId) || 0;
                        
                        const safeProgress = Math.max(statusData.progress_percent || 0, lastProgress);
                        const safePages = Math.max(statusData.pages_extracted || 0, lastPages);
                        
                        sessionManager.progressTracker.set(sessionId, safeProgress);
                        sessionManager.pageTracker.set(sessionId, safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Extracting page ${safePages} of ${statusData.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (statusData.status === 'complete') {
                            clearInterval(monitorInterval);
                            sessionManager.updateSession(sessionId, {
                                status: 'ready_for_ocr',
                                pageCount: statusData.pages_extracted,
                                extractionProgress: 100
                            });
                            
                            ModalManager.show(
                                'Extraction Complete',
                                `Successfully extracted ${statusData.pages_extracted} images from the PDF.`,
                                'success'
                            );
                        } else if (statusData.status === 'failed') {
                            clearInterval(monitorInterval);
                            sessionManager.updateSession(sessionId, { status: 'uploaded' });
                            throw new Error(statusData.error || 'Extraction failed');
                        }
                    }
                }
            } catch (error) {
                console.error('Error monitoring extraction:', error);
                if (error.message.includes('failed')) {
                    clearInterval(monitorInterval);
                    ModalManager.show('Extraction Failed', error.message, 'error');
                }
            }
        }, 5000); // Check every 5 seconds
        
    } catch (error) {
        console.error('Error creating extraction job:', error);
        ModalManager.show('Error', 'Failed to start extraction: ' + error.message, 'error');
        // Revert status
        sessionManager.updateSession(sessionId, { status: 'uploaded' });
    }
}

async function startOCR(sessionId) {
    const session = sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) return;
    
    // Update session status to ocr_processing
    sessionManager.updateSession(sessionId, { status: 'ocr_processing', ocrProgress: 0 });
    
    // Show progress modal
    ModalManager.showProgress('Running OCR', 'Starting OCR processing...', 0);
    
    try {
        // Create OCR job
        const response = await fetch('/api/jobs/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Email': getUserEmail()
            },
            body: JSON.stringify({
                session_id: sessionId,
                job_type: 'ocr',
                input_data: {
                    total_pages: session.pageCount,
                    start_page: 1
                }
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to create OCR job');
        }
        
        const job = await response.json();
        
        // Start monitoring the OCR progress via session_status.json
        const monitorInterval = setInterval(async () => {
            try {
                const statusUrl = `/storage/${session.userHash}/${sessionId}/session_status.json`;
                const statusResponse = await fetch(statusUrl);
                
                if (statusResponse.ok) {
                    const statusData = await statusResponse.json();
                    
                    if (statusData.stages && statusData.stages.ocr) {
                        const ocrStage = statusData.stages.ocr;
                        
                        // Get last known progress
                        const lastProgress = sessionManager.progressTracker.get(sessionId + '_ocr') || 0;
                        const lastPages = sessionManager.pageTracker.get(sessionId + '_ocr') || 0;
                        
                        const safeProgress = Math.max(ocrStage.progress_percent || 0, lastProgress);
                        const safePages = Math.max(ocrStage.pages_processed || 0, lastPages);
                        
                        sessionManager.progressTracker.set(sessionId + '_ocr', safeProgress);
                        sessionManager.pageTracker.set(sessionId + '_ocr', safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Processing page ${safePages} of ${ocrStage.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (ocrStage.status === 'complete') {
                            clearInterval(monitorInterval);
                            sessionManager.updateSession(sessionId, {
                                status: 'ocr_complete',
                                ocrProgress: 100,
                                ocrPagesProcessed: ocrStage.pages_processed
                            });
                            
                            ModalManager.show(
                                'OCR Complete',
                                `Successfully processed ${ocrStage.pages_processed} pages with OCR.`,
                                'success'
                            );
                        }
                    }
                }
            } catch (error) {
                console.error('Error monitoring OCR:', error);
            }
        }, 5000); // Check every 5 seconds
        
    } catch (error) {
        console.error('Error creating OCR job:', error);
        ModalManager.show('Error', 'Failed to start OCR: ' + error.message, 'error');
        // Revert status
        sessionManager.updateSession(sessionId, { status: 'ready_for_ocr' });
    }
}

// Export functions for inline onclick handlers
window.viewSession = viewSession;
window.closeModal = closeModal;
window.clearAllSessions = clearAllSessions;
window.startExtractPages = startExtractPages;
window.startOCR = startOCR;

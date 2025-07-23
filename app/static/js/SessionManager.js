import { ModalManager } from './ModalManager.js';
import { rebuildSessionStatus } from './api.js';
import { formatFileSize, escapeHtml } from './utils.js';

export class SessionManager {
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
        // On page load, always trigger a rebuild for all sessions to ensure UI is in sync.
        for (const session of this.sessions) {
            if (session.fileType === 'pdf' && session.userHash && session.sessionId) {
                console.info(`Triggering status rebuild for session ${session.sessionId} on page load.`);
                const rebuiltStatus = await rebuildSessionStatus(session.sessionId);
                if (rebuiltStatus) {
                    await this.processStatusData(session, rebuiltStatus);
                }
            }
        }
    }

    isStatusStale(statusData) {
        // Check if the status appears stale and needs rebuilding
        if (!statusData) {
            return true; // No status data means we should rebuild
        }
        
        // If no stages, always rebuild to get current format
        if (!statusData.stages) {
            return true;
        }
        
        // Check for extraction stage that shows processing but no progress
        const extractionStage = statusData.stages.page_extraction;
        if (extractionStage && 
            extractionStage.status === 'processing' && 
            extractionStage.pages_processed === 0 && 
            extractionStage.progress_percent === 0) {
            
            // ALWAYS consider this stale on page load - no time check needed
            // If it's truly processing, it should have some progress by now
            return true;
        }
        
        // Check for OCR stage that shows processing but no progress
        const ocrStage = statusData.stages.ocr;
        if (ocrStage && 
            ocrStage.status === 'processing' && 
            ocrStage.pages_processed === 0 && 
            ocrStage.progress_percent === 0) {
            
            // ALWAYS consider this stale too
            return true;
        }
        
        // Check if status is very old (more than 1 hour) - always rebuild old status
        if (statusData.updated_at) {
            const updatedTime = new Date(statusData.updated_at);
            const now = new Date();
            const timeDiff = now - updatedTime;
            const oneHourInMs = 60 * 60 * 1000;
            
            if (timeDiff > oneHourInMs) {
                return true; // Very old status, rebuild to be sure
            }
        }
        
        return false;
    }

    async processStatusData(session, statusData) {
        // Process status data and update session accordingly
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
                        ocrPagesProcessed: ocrStage.pages_processed,
                        ocrResults: ocrStage.results
                    });
                } else if (ocrStage.status === 'ocr_processing') {
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
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); window.startExtractPages('${session.sessionId}')">Extract Images</button>`;
            } else if (session.status === 'uploaded' && session.fileType === 'image') {
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); window.startOCR('${session.sessionId}')">Start OCR</button>`;
            } else if (session.status === 'ready_for_ocr') {
                actionButton = `<button class="action-button" onclick="event.stopPropagation(); window.startOCR('${session.sessionId}')">Start OCR</button>`;
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
                <div class="session-item" onclick="window.viewSession('${session.sessionId}')">
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

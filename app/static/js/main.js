import { SessionManager } from './SessionManager.js';
import { FileUploader } from './FileUploader.js';
import { ModalManager } from './ModalManager.js';
import { getUserEmail, escapeHtml } from './utils.js';
import { createJob } from './api.js';

// Global instances
window.sessionManager = null;
window.uploader = null;

// Helper functions exposed globally for inline HTML event handlers
window.viewSession = (sessionId) => {
    const session = window.sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) {
        ModalManager.show('Session Not Found', 'Session not found in local history', 'error');
        return;
    }

    const content = `
        <div class="session-details">
            <p><strong>Session ID:</strong> ${session.sessionId}</p>
            <p><strong>Uploaded:</strong> ${new Date(session.uploadedAt).toLocaleString()}</p>
            <p><strong>Size:</strong> ${session.fileSize ? (session.fileSize / (1024 * 1024)).toFixed(2) + ' MB' : 'N/A'}</p>
            <p><strong>Upload Method:</strong> ${session.uploadMethod || 'normal'}</p>
            <p><strong>Status:</strong> <span class="session-status status-${session.status}">${session.status}</span></p>
            ${session.pageCount ? `<p><strong>Pages:</strong> ${session.pageCount}</p>` : ''}
            
            <a href="/storage/${session.userHash}/${session.sessionId}/${session.filename}" 
               target="_blank" 
               class="upload-button file-link">
                View File
            </a>

            ${session.ocrResults ? `
                <div class="ocr-results-container">
                    <h3>OCR Results</h3>
                    <div class="ocr-results">
                        ${Object.entries(session.ocrResults).map(([pageNum, text]) => `
                            <div class="ocr-page">
                                <h4>Page ${pageNum}</h4>
                                <pre>${escapeHtml(text)}</pre>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        </div>
    `;

    ModalManager.show(session.filename, content);
};

window.closeModal = () => {
    ModalManager.close();
};

window.clearAllSessions = () => {
    window.sessionManager.clearAll();
};

window.startExtractPages = async (sessionId) => {
    const session = window.sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) return;
    
    // Update session status to processing
    window.sessionManager.updateSession(sessionId, { status: 'processing', extractionProgress: 0 });
    
    // Show progress modal
    ModalManager.showProgress('Extracting Images', 'Starting extraction...', 0);
    
    try {
        // Create extraction job
        const job = await createJob(sessionId, 'extract_pages', {
            filename: session.filename
        });
        
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
                        const lastProgress = window.sessionManager.progressTracker.get(sessionId + '_extraction') || 0;
                        const lastPages = window.sessionManager.pageTracker.get(sessionId + '_extraction') || 0;
                        
                        const safeProgress = Math.max(extractionStage.progress_percent || 0, lastProgress);
                        const safePages = Math.max(extractionStage.pages_processed || 0, lastPages);
                        
                        window.sessionManager.progressTracker.set(sessionId + '_extraction', safeProgress);
                        window.sessionManager.pageTracker.set(sessionId + '_extraction', safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Extracting page ${safePages} of ${extractionStage.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (extractionStage.status === 'complete') {
                            clearInterval(monitorInterval);
                            window.sessionManager.updateSession(sessionId, {
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
                        const lastProgress = window.sessionManager.progressTracker.get(sessionId) || 0;
                        const lastPages = window.sessionManager.pageTracker.get(sessionId) || 0;
                        
                        const safeProgress = Math.max(statusData.progress_percent || 0, lastProgress);
                        const safePages = Math.max(statusData.pages_extracted || 0, lastPages);
                        
                        window.sessionManager.progressTracker.set(sessionId, safeProgress);
                        window.sessionManager.pageTracker.set(sessionId, safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Extracting page ${safePages} of ${statusData.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (statusData.status === 'complete') {
                            clearInterval(monitorInterval);
                            window.sessionManager.updateSession(sessionId, {
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
                            window.sessionManager.updateSession(sessionId, { status: 'uploaded' });
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
        window.sessionManager.updateSession(sessionId, { status: 'uploaded' });
    }
};

window.startOCR = async (sessionId) => {
    const session = window.sessionManager.sessions.find(s => s.sessionId === sessionId);
    if (!session) return;
    
    // Update session status to ocr_processing
    window.sessionManager.updateSession(sessionId, { status: 'ocr_processing', ocrProgress: 0 });
    
    // Show progress modal
    ModalManager.showProgress('Running OCR', 'Starting OCR processing...', 0);
    
    try {
        // Create OCR job
        const job = await createJob(sessionId, 'ocr', {
            total_pages: session.pageCount,
            start_page: 1
        });
        
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
                        const lastProgress = window.sessionManager.progressTracker.get(sessionId + '_ocr') || 0;
                        const lastPages = window.sessionManager.pageTracker.get(sessionId + '_ocr') || 0;
                        
                        const safeProgress = Math.max(ocrStage.progress_percent || 0, lastProgress);
                        const safePages = Math.max(ocrStage.pages_processed || 0, lastPages);
                        
                        window.sessionManager.progressTracker.set(sessionId + '_ocr', safeProgress);
                        window.sessionManager.pageTracker.set(sessionId + '_ocr', safePages);
                        
                        // Update progress modal
                        ModalManager.updateProgress(
                            `Processing page ${safePages} of ${ocrStage.total_pages || '?'}...`,
                            safeProgress
                        );
                        
                        if (ocrStage.status === 'complete') {
                            clearInterval(monitorInterval);
                            window.sessionManager.updateSession(sessionId, {
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
        window.sessionManager.updateSession(sessionId, { status: 'ready_for_ocr' });
    }
};

// Initialize everything when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize managers
    window.sessionManager = new SessionManager();
    window.uploader = new FileUploader(window.sessionManager);
    
    // Update user email display
    document.getElementById('user-email').textContent = getUserEmail();
    
    // Set up modal close handler
    window.onclick = function(event) {
        const modal = document.getElementById('session-modal');
        if (event.target === modal) {
            window.closeModal();
        }
    };
    
    // Set up keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            window.closeModal();
        }
    });
});
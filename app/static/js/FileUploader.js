import { ModalManager } from './ModalManager.js';
import { computeUserHash, getUserEmail, formatFileSize } from './utils.js';

const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
const MAX_NORMAL_UPLOAD_SIZE = 20 * 1024 * 1024; // 20MB

export class FileUploader {
    constructor(sessionManager) {
        this.sessionManager = sessionManager;
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
        this.sessionManager.addSession({
            sessionId: data.session_id,
            filename: file.name,
            fileSize: file.size,
            fileType: this.getFileType(file.name),
            uploadedAt: new Date().toISOString(),
            status: 'uploaded',
            userHash: await computeUserHash(getUserEmail()),
            uploadMethod: 'normal'
        });
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
                                this.sessionManager.addSession({
                                    sessionId: session_id,
                                    filename: file.name,
                                    fileSize: file.size,
                                    fileType: this.getFileType(file.name),
                                    uploadedAt: new Date().toISOString(),
                                    status: 'uploaded',
                                    userHash: userHash,
                                    uploadMethod: 'chunked'
                                });
                                
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
            window.viewSession(session_id);
        }, 500);
    }
}
import { getUserEmail } from './utils.js';

export async function rebuildSessionStatus(sessionId) {
    // Rebuild session status by calling the API endpoint
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

export async function createJob(sessionId, jobType, inputData) {
    const response = await fetch('/api/jobs/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-User-Email': getUserEmail()
        },
        body: JSON.stringify({
            session_id: sessionId,
            job_type: jobType,
            input_data: inputData
        })
    });

    if (!response.ok) {
        throw new Error('Failed to create job');
    }

    return await response.json();
}
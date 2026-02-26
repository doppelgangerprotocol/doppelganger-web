/**
 * SSE — used only by Alice to wait for Bob's verification result.
 * Bob gets his result synchronously from the POST /verify response.
 */

function connectAliceSSE(sessionId, onEvent) {
    const es = new EventSource(`/api/session/${sessionId}/stream`);
    es.onmessage = (e) => onEvent(JSON.parse(e.data));
    es.onerror = () => console.error("[sse] connection lost");
    return es;
}
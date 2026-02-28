/**
 * debug.js — Doppelgänger Protocol live debug panel
 *
 * Renders a sliding panel showing cryptographic operations in real time.
 * Completely decoupled from protocol logic — call ProtocolLog.emit()
 * from anywhere and it appears here.
 *
 * Event types and their colors:
 *   key      — ECDH key generation, derivation
 *   network  — API calls, SSE events
 *   embed    — embedding vectors, cosine similarity
 *   score    — pass/fail scoring
 *   phase    — Redis session phase transitions
 *   info     — general protocol info
 */

const ProtocolLog = (() => {

    let isOpen = false;
    let entryCount = 0;

    // ── Bootstrap ──────────────────────────────────────────────────────────

    function init() {
        injectHTML();
        injectCSS();
        bindEvents();
    }

    function injectHTML() {
        // Floating trigger button
        const trigger = document.createElement("button");
        trigger.id = "debug-trigger";
        trigger.innerHTML = `
            <span class="debug-trigger-icon">⌥</span>
            <span class="debug-trigger-label">Protocol Log</span>
        `;
        trigger.setAttribute("aria-label", "Open Protocol Log");

        // Panel
        const panel = document.createElement("div");
        panel.id = "debug-panel";
        panel.setAttribute("aria-hidden", "true");
        panel.innerHTML = `
            <div class="debug-header">
                <div class="debug-title">
                    <span class="debug-title-icon">⌥</span>
                    <span>Protocol Log</span>
                    <span class="debug-live-dot" id="debug-live-dot"></span>
                    <span class="debug-live-label">LIVE</span>
                </div>
                <div class="debug-header-actions">
                    <button class="debug-clear" id="debug-clear" title="Clear log">Clear</button>
                    <button class="debug-close" id="debug-close" title="Close panel">✕</button>
                </div>
            </div>
            <div class="debug-legend">
                <span class="legend-item key">KEY</span>
                <span class="legend-item network">NET</span>
                <span class="legend-item embed">EMBED</span>
                <span class="legend-item score">SCORE</span>
                <span class="legend-item phase">PHASE</span>
            </div>
            <div class="debug-log" id="debug-log">
                <div class="debug-empty">
                    Waiting for protocol events...
                </div>
            </div>
            <div class="debug-footer">
                <span id="debug-entry-count">0 events</span>
                <span>doppelgangerprotocol.app</span>
            </div>
        `;

        // Overlay (click outside to close)
        const overlay = document.createElement("div");
        overlay.id = "debug-overlay";

        document.body.appendChild(trigger);
        document.body.appendChild(panel);
        document.body.appendChild(overlay);
    }

    function injectCSS() {
        const style = document.createElement("style");
        style.textContent = `
            /* ── Trigger button ───────────────────────────────── */
            #debug-trigger {
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 900;
                display: flex;
                align-items: center;
                gap: 8px;
                background: var(--text);
                color: var(--bg);
                border: none;
                padding: 10px 16px;
                font-family: var(--mono);
                font-size: 12px;
                font-weight: 700;
                border-radius: 3px;
                cursor: pointer;
                letter-spacing: 0.5px;
                box-shadow: 0 2px 12px rgba(0,0,0,0.15);
                transition: opacity 0.15s;
            }

            #debug-trigger:hover { opacity: 0.8; }

            .debug-trigger-icon {
                font-size: 14px;
                opacity: 0.7;
            }

            /* ── Overlay ──────────────────────────────────────── */
            #debug-overlay {
                display: none;
                position: fixed;
                inset: 0;
                z-index: 910;
                background: rgba(26, 24, 20, 0.3);
            }

            #debug-overlay.visible { display: block; }

            /* ── Panel ────────────────────────────────────────── */
            #debug-panel {
                position: fixed;
                top: 0;
                right: -480px;
                width: 440px;
                max-width: 92vw;
                height: 100vh;
                z-index: 920;
                background: var(--bg);
                border-left: 1px solid var(--border);
                display: flex;
                flex-direction: column;
                transition: right 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                font-family: var(--mono);
            }

            #debug-panel.open {
                right: 0;
                box-shadow: -8px 0 32px rgba(26,24,20,0.12);
            }

            /* ── Header ───────────────────────────────────────── */
            .debug-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 16px 20px;
                border-bottom: 1px solid var(--border);
                flex-shrink: 0;
            }

            .debug-title {
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 13px;
                font-weight: 700;
                color: var(--text);
                letter-spacing: 0.5px;
            }

            .debug-title-icon { opacity: 0.5; }

            .debug-live-dot {
                width: 6px;
                height: 6px;
                background: var(--text-muted);
                border-radius: 50%;
                flex-shrink: 0;
                transition: background 0.3s;
            }

            .debug-live-dot.active {
                background: #2d7a4f;
                animation: pulse 1.5s ease-in-out infinite;
            }

            .debug-live-label {
                font-size: 9px;
                color: var(--text-muted);
                letter-spacing: 2px;
            }

            .debug-header-actions {
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .debug-clear, .debug-close {
                background: none;
                border: 1px solid var(--border);
                color: var(--text-muted);
                font-family: var(--mono);
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 2px;
                cursor: pointer;
                transition: color 0.15s, border-color 0.15s;
            }

            .debug-clear:hover, .debug-close:hover {
                color: var(--text);
                border-color: var(--text);
            }

            /* ── Legend ───────────────────────────────────────── */
            .debug-legend {
                display: flex;
                gap: 8px;
                padding: 10px 20px;
                border-bottom: 1px solid var(--border);
                flex-shrink: 0;
            }

            .legend-item {
                font-size: 9px;
                letter-spacing: 1.5px;
                padding: 2px 6px;
                border-radius: 2px;
                font-weight: 700;
            }

            .legend-item.key     { background: #e8f0eb; color: #2d5a3d; }
            .legend-item.network { background: #e8eaf0; color: #2d3d5a; }
            .legend-item.embed   { background: #f0ebe8; color: #5a3d2d; }
            .legend-item.score   { background: #f0ebe8; color: #8b2020; }
            .legend-item.phase   { background: #ede8f0; color: #3d2d5a; }

            /* ── Log area ─────────────────────────────────────── */
            .debug-log {
                flex: 1;
                overflow-y: auto;
                padding: 12px 0;
            }

            .debug-empty {
                padding: 40px 20px;
                color: var(--text-muted);
                font-size: 12px;
                text-align: center;
                font-style: italic;
            }

            /* ── Log entry ────────────────────────────────────── */
            .debug-entry {
                padding: 10px 20px;
                border-bottom: 1px solid var(--border);
                animation: fadeIn 0.2s ease;
            }

            .debug-entry:last-child { border-bottom: none; }

            .debug-entry-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 6px;
            }

            .debug-entry-type {
                font-size: 9px;
                letter-spacing: 1.5px;
                padding: 2px 6px;
                border-radius: 2px;
                font-weight: 700;
                flex-shrink: 0;
            }

            .debug-entry-type.key     { background: #e8f0eb; color: #2d5a3d; }
            .debug-entry-type.network { background: #e8eaf0; color: #2d3d5a; }
            .debug-entry-type.embed   { background: #f0ebe8; color: #5a3d2d; }
            .debug-entry-type.score   { background: #f0f0e8; color: #5a4f2d; }
            .debug-entry-type.phase   { background: #ede8f0; color: #3d2d5a; }
            .debug-entry-type.info    { background: var(--surface); color: var(--text-muted); }

            .debug-entry-title {
                font-size: 12px;
                font-weight: 700;
                color: var(--text);
                flex: 1;
            }

            .debug-entry-time {
                font-size: 10px;
                color: var(--text-muted);
                flex-shrink: 0;
            }

            .debug-entry-body {
                font-size: 11px;
                color: var(--text-muted);
                line-height: 1.6;
                word-break: break-all;
                white-space: pre-wrap;
            }

            .debug-value {
                color: var(--text);
                font-weight: 600;
            }

            .debug-array {
                display: block;
                margin-top: 4px;
                padding: 6px 10px;
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: 2px;
                font-size: 10px;
                color: var(--text);
                line-height: 1.8;
            }

            /* ── Footer ───────────────────────────────────────── */
            .debug-footer {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 20px;
                border-top: 1px solid var(--border);
                font-size: 10px;
                color: var(--text-muted);
                flex-shrink: 0;
            }

            /* ── Mobile ───────────────────────────────────────── */
            @media (max-width: 480px) {
                #debug-panel {
                    width: 100vw;
                    max-width: 100vw;
                }

                #debug-trigger {
                    bottom: 16px;
                    right: 16px;
                    padding: 10px 14px;
                }

                .debug-trigger-label { display: none; }
            }
        `;
        document.head.appendChild(style);
    }

    function bindEvents() {
        document.getElementById("debug-trigger").addEventListener("click", open);
        document.getElementById("debug-close").addEventListener("click", close);
        document.getElementById("debug-overlay").addEventListener("click", close);
        document.getElementById("debug-clear").addEventListener("click", clear);
    }

    // ── Panel open/close ───────────────────────────────────────────────────

    function open() {
        isOpen = true;
        document.getElementById("debug-panel").classList.add("open");
        document.getElementById("debug-panel").setAttribute("aria-hidden", "false");
        document.getElementById("debug-overlay").classList.add("visible");
        // Scroll to bottom when opening
        scrollToBottom();
    }

    function close() {
        isOpen = false;
        document.getElementById("debug-panel").classList.remove("open");
        document.getElementById("debug-panel").setAttribute("aria-hidden", "true");
        document.getElementById("debug-overlay").classList.remove("visible");
    }

    function clear() {
        entryCount = 0;
        document.getElementById("debug-log").innerHTML =
            '<div class="debug-empty">Waiting for protocol events...</div>';
        document.getElementById("debug-entry-count").textContent = "0 events";
        document.getElementById("debug-live-dot").classList.remove("active");
    }

    // ── Emit a log entry ───────────────────────────────────────────────────

    /**
     * emit(type, title, data)
     *
     * type:  "key" | "network" | "embed" | "score" | "phase" | "info"
     * title: short description shown in bold
     * data:  object with key-value pairs to display, or null
     *
     * Examples:
     *   ProtocolLog.emit("key", "Alice keypair generated", {
     *       curve: "P-256",
     *       public_x: jwk.x.slice(0, 12) + "...",
     *       public_y: jwk.y.slice(0, 12) + "...",
     *       extractable: false
     *   });
     */
    function emit(type, title, data = null) {
        entryCount++;

        // Remove empty state
        const log = document.getElementById("debug-log");
        const empty = log.querySelector(".debug-empty");
        if (empty) empty.remove();

        // Pulse the live dot
        const dot = document.getElementById("debug-live-dot");
        dot.classList.add("active");

        // Timestamp
        const now = new Date();
        const time = now.toLocaleTimeString("en-US", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        }) + "." + String(now.getMilliseconds()).padStart(3, "0");

        // Build entry
        const entry = document.createElement("div");
        entry.className = "debug-entry";

        let bodyHTML = "";
        if (data) {
            bodyHTML = '<div class="debug-entry-body">';
            for (const [key, value] of Object.entries(data)) {
                if (Array.isArray(value)) {
                    bodyHTML += `${key}:\n`;
                    bodyHTML += `<code class="debug-array">[${value.join(", ")}]</code>`;
                } else {
                    bodyHTML += `${key}: <span class="debug-value">${value}</span>\n`;
                }
            }
            bodyHTML += '</div>';
        }

        entry.innerHTML = `
            <div class="debug-entry-header">
                <span class="debug-entry-type ${type}">${type.toUpperCase()}</span>
                <span class="debug-entry-title">${title}</span>
                <span class="debug-entry-time">${time}</span>
            </div>
            ${bodyHTML}
        `;

        log.appendChild(entry);

        // Update count
        document.getElementById("debug-entry-count").textContent =
            `${entryCount} event${entryCount !== 1 ? "s" : ""}`;

        // Auto-scroll if panel is open
        if (isOpen) scrollToBottom();
    }

    function scrollToBottom() {
        const log = document.getElementById("debug-log");
        if (log) log.scrollTop = log.scrollHeight;
    }

    // ── Convenience emitters ───────────────────────────────────────────────
    // Pre-formatted for each protocol event type

    function keyGenerated(role, jwk) {
        emit("key", `${role} keypair generated`, {
            algorithm: "ECDH P-256",
            "public_x": jwk.x.slice(0, 16) + "...",
            "public_y": jwk.y.slice(0, 16) + "...",
            "private_key": "non-extractable — stays in browser",
            "key_ops": "deriveKey only"
        });
    }

    function sessionCreated(sessionId) {
        emit("network", "POST /api/session → 201 Created", {
            session_id: sessionId.slice(0, 16) + "...",
            phase: "WAITING_FOR_BOB",
            answer_stored: "embedding vector only — raw text discarded"
        });
    }

    function embeddingReceived(vector) {
        const preview = vector.slice(0, 8).map(v => v.toFixed(4));
        emit("embed", "Answer embedded → vector stored", {
            model: "all-MiniLM-L6-v2",
            dimensions: vector.length,
            "preview [0..7]": preview
        });
    }

    function similarityScored(score, result) {
        emit("score", `Cosine similarity → ${result}`, {
            score: `${score}%`,
            threshold: "75%",
            result: result,
            "key_exchange": result === "PASS"
                ? "alice_pubkey_jwk released to Bob"
                : "alice_pubkey_jwk withheld"
        });
    }

    function phaseTransition(from, to) {
        emit("phase", `Session phase: ${from} → ${to}`, {
            stored_in: "Redis",
            ttl: "30 minutes",
            one_time_use: "session locked after first verify attempt"
        });
    }

    function sseEvent(eventData) {
        emit("network", `SSE event received: ${eventData.event}`, {
            event: eventData.event,
            score: eventData.score !== undefined ? `${eventData.score}%` : "—",
            bob_pubkey: eventData.bob_pubkey_jwk
                ? eventData.bob_pubkey_jwk.x.slice(0, 16) + "..."
                : "—"
        });
    }

    function ecdhDerived(role) {
        emit("key", `${role} derived shared AES-GCM key`, {
            algorithm: "ECDH → AES-GCM-256",
            method: "deriveKey(ECDH, theirPublicKey, myPrivateKey)",
            key_length: "256 bits",
            extractable: "false — stays in browser",
            note: "Alice and Bob now share the same key without transmitting it"
        });
    }

    function sessionFetched(phase, aliceName) {
        emit("network", `GET /api/session → phase: ${phase}`, {
            alice_name: aliceName,
            phase: phase,
            alice_pubkey_jwk: "withheld until Bob passes verification"
        });
    }

    function verifySubmitted() {
        emit("network", "POST /api/session/verify → scoring...", {
            bob_answer: "embedded client-side → vector sent",
            alice_pubkey: "conditionally released on PASS only"
        });
    }

    // Public API
    return {
        init,
        emit,
        keyGenerated,
        sessionCreated,
        embeddingReceived,
        similarityScored,
        phaseTransition,
        sseEvent,
        ecdhDerived,
        sessionFetched,
        verifySubmitted
    };

})();

// Auto-init when DOM is ready
document.addEventListener("DOMContentLoaded", () => ProtocolLog.init());
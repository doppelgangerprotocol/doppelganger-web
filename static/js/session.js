/**
 * session.js — Doppelgänger Protocol state machine
 *
 * Alice flow:
 *   initAlice() → generateKeyPair() → create() → connectAliceSSE() → wait
 *
 * Bob flow:
 *   initBob(sessionId) → generateKeyPair() → fetchSession() → submitAnswer()
 *
 * ProtocolLog.emit() is called at every meaningful protocol event
 * so the debug panel shows exactly what's happening cryptographically.
 */

const Session = (() => {

    let aliceKeyPair    = null;
    let bobKeyPair      = null;
    let currentSessionId = null;
    let currentLink     = null;

    // ── Alice ──────────────────────────────────────────────────────────────

    async function initAlice() {
        UI.showStep("step-landing");

        // Generate keypair immediately — before Alice even fills the form.
        // By the time she hits submit, keys are ready.
        try {
            ProtocolLog.emit("key", "Generating Alice ECDH P-256 keypair...", {
                algorithm: "ECDH",
                curve: "P-256",
                extractable: "false — private key stays in this browser tab"
            });

            aliceKeyPair = await Crypto.generateKeyPair();
            const jwk = await Crypto.exportPublicKey(aliceKeyPair.publicKey);
            ProtocolLog.keyGenerated("Alice", jwk);

            const keyStatus = document.getElementById("key-status");
            const keyStatusText = document.getElementById("key-status-text");
            if (keyStatus) {
                keyStatus.classList.add("ready");
                keyStatusText.textContent = "✓ Encryption keys ready";
            }
            const createBtn = document.getElementById("create-btn");
            if (createBtn) createBtn.disabled = false;

        } catch (err) {
            console.error("[session] Key generation failed:", err);
            ProtocolLog.emit("key", "Keypair generation failed", { error: err.message });
        }
    }

    async function create() {
        const aliceName      = document.getElementById("alice-name").value.trim();
        const memoryQuestion = document.getElementById("memory-question").value.trim();
        const memoryAnswer   = document.getElementById("memory-answer").value.trim();

        if (!aliceName || !memoryQuestion || !memoryAnswer) {
            alert("Please fill in all fields.");
            return;
        }
        if (!aliceKeyPair) {
            alert("Keys still generating — please wait a moment.");
            return;
        }

        const createBtn = document.getElementById("create-btn");
        createBtn.disabled = true;
        createBtn.textContent = "Creating...";

        try {
            const alicePubkeyJwk = await Crypto.exportPublicKey(aliceKeyPair.publicKey);

            ProtocolLog.emit("network", "POST /api/session → creating session", {
                alice_name: aliceName,
                question: memoryQuestion,
                answer: "being embedded via temporary embedding service",
                alice_pubkey_x: alicePubkeyJwk.x.slice(0, 16) + "...",
            });

            const resp = await fetch("/api/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    alice_name:       aliceName,
                    memory_question:  memoryQuestion,
                    memory_answer:    memoryAnswer,
                    alice_pubkey_jwk: alicePubkeyJwk
                })
            });

            if (!resp.ok) {
                const err = await resp.json();
                alert(`Error: ${err.error}`);
                createBtn.disabled = false;
                createBtn.textContent = "Generate Challenge Link";
                return;
            }

            const data = await resp.json();
            currentSessionId = data.session_id;
            currentLink = data.link;

            ProtocolLog.sessionCreated(data.session_id);
            ProtocolLog.phaseTransition("—", "WAITING_FOR_BOB");

            document.getElementById("session-link").textContent = data.link;
            document.getElementById("qr-code").src = data.qr_code;
            UI.showStep("step-waiting");
            // ── Vector preview ─────────────────────────────────────────────
            const previewBlock = document.getElementById("vector-preview-block");
            const previewEl    = document.getElementById("vector-preview");
            const labelEl      = document.getElementById("vector-question-label");
            const dimsEl       = document.getElementById("vector-dimensions");

            if (data.vector_preview && previewBlock) {
                labelEl.textContent = memoryQuestion.slice(0, 60) + (memoryQuestion.length > 60 ? "..." : "");
                dimsEl.textContent  = data.vector_dimensions;
                previewEl.textContent = "[" + data.vector_preview.join(", ") + "...]";
                previewBlock.style.display = "block";

                // Log to protocol panel
                // ProtocolLog.embeddingReceived(data.vector_preview);
                ProtocolLog.embeddingReceived(data.vector_preview, data.vector_dimensions);
            }
            // ── End vector preview ──────────────────────────────────────────
            connectAliceSSE(data.session_id);

        } catch (err) {
            console.error("[session] create failed:", err);
            ProtocolLog.emit("network", "Session creation failed", { error: err.message });
            alert("Something went wrong. Please try again.");
            createBtn.disabled = false;
            createBtn.textContent = "Generate Challenge Link";
        }
    }

    function connectAliceSSE(sessionId) {
        ProtocolLog.emit("network", "SSE stream opened — waiting for Bob", {
            endpoint: `/api/session/${sessionId.slice(0, 12)}.../stream`,
            transport: "Server-Sent Events",
            waiting_for: "VERIFIED or FAILED event"
        });

        const es = new EventSource(`/api/session/${sessionId}/stream`);

        es.onmessage = async (e) => {
            const event = JSON.parse(e.data);
            ProtocolLog.sseEvent(event);

            if (event.event === "VERIFIED") {
                es.close();

                ProtocolLog.emit("key", "Importing Bob's public key from SSE event", {
                    algorithm: "ECDH P-256",
                    bob_pubkey_x: event.bob_pubkey_jwk.x.slice(0, 16) + "...",
                    source: "SSE stream — only released because Bob passed"
                });

                const bobPubkey  = await Crypto.importPublicKey(event.bob_pubkey_jwk);
                const sharedKey  = await Crypto.deriveSharedKey(aliceKeyPair.privateKey, bobPubkey);
                ProtocolLog.ecdhDerived("Alice");

                document.getElementById("alice-score").textContent = `${event.score}% match ✓`;
                ProtocolLog.phaseTransition("WAITING_FOR_BOB", "VERIFIED");
                UI.showStep("step-alice-pass");
            }

            if (event.event === "FAILED") {
                es.close();
                ProtocolLog.phaseTransition("WAITING_FOR_BOB", "FAILED");
                document.getElementById("alice-fail-score").textContent = `${event.score}% match`;
                UI.showStep("step-alice-fail");
            }
        };

        es.onerror = () => {
            ProtocolLog.emit("network", "SSE connection error", {
                note: "Stream may have closed after terminal event — this is normal"
            });
        };
    }

    function copyLink() {
        if (!currentLink) return;
        navigator.clipboard.writeText(currentLink)
            .then(() => {
                const btn = document.querySelector(".link-box .btn-secondary");
                if (btn) {
                    btn.textContent = "Copied!";
                    setTimeout(() => btn.textContent = "Copy", 2000);
                }
            })
            .catch(() => alert("Copy failed — select the link and copy manually"));
    }

    // ── Reset (called before "Start New Verification" / "Try Again") ───────

    function reset() {
        // Clear form fields
        document.getElementById("alice-name").value       = "";
        document.getElementById("memory-question").value  = "";
        document.getElementById("memory-answer").value    = "";

        // Reset char counters
        document.getElementById("q-count").textContent = "0";
        document.getElementById("a-count").textContent = "0";

        // Reset button state
        const createBtn = document.getElementById("create-btn");
        if (createBtn) {
            createBtn.textContent = "Generate Challenge Link";
            createBtn.disabled = true;
        }

        // Reset key status
        const keyStatus = document.getElementById("key-status");
        const keyStatusText = document.getElementById("key-status-text");
        if (keyStatus) {
            keyStatus.classList.remove("ready");
            keyStatusText.textContent = "Generating your encryption keys...";
        }

        // Clear session state
        currentSessionId = null;
        currentLink      = null;

        // Generate a fresh keypair for the next session
        ProtocolLog.emit("key", "Generating fresh keypair for new session", {
            reason: "Previous session complete — new ECDH keys required",
            previous_keys: "discarded"
        });

        Crypto.generateKeyPair().then(async kp => {
            aliceKeyPair = kp;
            const jwk = await Crypto.exportPublicKey(kp.publicKey);
            ProtocolLog.keyGenerated("Alice (new session)", jwk);
            if (keyStatus) keyStatus.classList.add("ready");
            if (keyStatusText) keyStatusText.textContent = "✓ Encryption keys ready";
            if (createBtn) createBtn.disabled = false;
        });
    }

    // ── Bob ────────────────────────────────────────────────────────────────

    async function initBob(sessionId) {
        UI.showStep("step-loading");

        ProtocolLog.emit("key", "Generating Bob ECDH P-256 keypair...", {
            algorithm: "ECDH",
            curve: "P-256",
            extractable: "false — private key stays in this browser tab"
        });

        // Generate Bob's keypair immediately
        try {
            bobKeyPair = await Crypto.generateKeyPair();
            const jwk = await Crypto.exportPublicKey(bobKeyPair.publicKey);
            ProtocolLog.keyGenerated("Bob", jwk);

            const keyStatus = document.getElementById("bob-key-status");
            if (keyStatus) {
                keyStatus.innerHTML =
                    '<span style="color:var(--success, #1a5c35)">✓ Encryption keys ready</span>';
            }
            const submitBtn = document.getElementById("submit-btn");
            if (submitBtn) submitBtn.disabled = false;

        } catch (err) {
            console.error("[session] Bob key generation failed:", err);
            ProtocolLog.emit("key", "Bob keypair generation failed", { error: err.message });
        }

        // Fetch the session to get Alice's question
        try {
            ProtocolLog.emit("network", `GET /api/session/${sessionId.slice(0, 12)}...`, {
                note: "alice_pubkey_jwk is withheld at this stage"
            });

            const resp = await fetch(`/api/session/${sessionId}`);

            if (resp.status === 404) {
                ProtocolLog.emit("network", "Session not found → 404", {
                    session_id: sessionId.slice(0, 12) + "...",
                    reason: "expired or never existed"
                });
                UI.showStep("step-expired");
                return;
            }

            const data = await resp.json();

            if (data.phase !== "WAITING_FOR_BOB") {
                ProtocolLog.emit("phase", `Session already used — phase: ${data.phase}`, {
                    reason: "one-time use — session locked after first verify attempt"
                });
                UI.showStep("step-expired");
                return;
            }

            ProtocolLog.sessionFetched(data.phase, data.alice_name);

            document.getElementById("alice-name-display").textContent = data.alice_name;
            document.getElementById("challenge-question").textContent = data.memory_question;
            UI.showStep("step-bob-challenge");

        } catch (err) {
            console.error("[session] initBob fetch failed:", err);
            ProtocolLog.emit("network", "Session fetch failed", { error: err.message });
            UI.showStep("step-expired");
        }
    }

    async function submitAnswer() {
        const bobName = document.getElementById("bob-name").value.trim();
        const answer  = document.getElementById("bob-answer").value.trim();

        if (!bobName || !answer) {
            alert("Please fill in your name and answer.");
            return;
        }
        if (!bobKeyPair) {
            alert("Keys still generating — please wait.");
            return;
        }

        const submitBtn = document.getElementById("submit-btn");
        submitBtn.disabled  = true;
        submitBtn.textContent = "Submitting...";
        UI.showStep("step-scoring");

        try {
            const bobPubkeyJwk = await Crypto.exportPublicKey(bobKeyPair.publicKey);

            ProtocolLog.verifySubmitted();
            ProtocolLog.emit("embed", "Answer being embedded on server", {
                answer_preview: answer.slice(0, 30) + (answer.length > 30 ? "..." : ""),
                model: "all-MiniLM-L6-v2",
                dimensions: 384,
                note: "Server computes cosine similarity against Alice's stored vector"
            });

            const resp = await fetch(`/api/session/${SESSION_ID}/verify`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    bob_name:       bobName,
                    answer:         answer,
                    bob_pubkey_jwk: bobPubkeyJwk
                })
            });

            const data = await resp.json();
            ProtocolLog.similarityScored(data.score, data.result);

            if (data.result === "PASS") {
                ProtocolLog.phaseTransition("WAITING_FOR_BOB", "VERIFIED");

                ProtocolLog.emit("key", "Received alice_pubkey_jwk — Bob passed verification", {
                    alice_pubkey_x: data.alice_pubkey_jwk.x.slice(0, 16) + "...",
                    note: "This key was withheld until Bob proved himself"
                });

                const alicePubkey = await Crypto.importPublicKey(data.alice_pubkey_jwk);
                const sharedKey   = await Crypto.deriveSharedKey(bobKeyPair.privateKey, alicePubkey);
                ProtocolLog.ecdhDerived("Bob");

                document.getElementById("bob-score").textContent = `${data.score}% match ✓`;
                UI.showStep("step-bob-pass");

            } else {
                ProtocolLog.phaseTransition("WAITING_FOR_BOB", "FAILED");
                ProtocolLog.emit("key", "alice_pubkey_jwk withheld — FAIL", {
                    reason: "score below threshold",
                    key_exchange: "did not occur",
                    session: "locked — cannot retry"
                });

                document.getElementById("bob-fail-score").textContent = `${data.score}% match`;
                UI.showStep("step-bob-fail");
            }

        } catch (err) {
            console.error("[session] submitAnswer failed:", err);
            ProtocolLog.emit("network", "Verify request failed", { error: err.message });
            alert("Something went wrong. Please try again.");
            UI.showStep("step-bob-challenge");
            submitBtn.disabled  = false;
            submitBtn.textContent = "Submit Answer";
        }
    }

    return { initAlice, create, copyLink, reset, initBob, submitAnswer };

})();
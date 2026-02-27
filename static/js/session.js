/**
 * Session — Doppelganger Protocol state machine
 *
 * Alice flow:
 *   initAlice() → generate keys → user fills form → create() → connectSSE() → wait
 *
 * Bob flow:
 *   initBob(sessionId) → fetch session → generate keys → user fills form → submitAnswer()
 */

const Session = (() => {

    let aliceKeyPair = null;
    let bobKeyPair = null;
    let currentSessionId = null;
    let currentLink = null;

    // ─── Alice ────────────────────────────────────────────────────────────────

    async function initAlice() {
        UI.showStep("step-landing");

        // Pre-generate Alice's keypair in the background while she fills the form
        try {
            aliceKeyPair = await Crypto.generateKeyPair();
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
        }
    }

    async function create() {
        const aliceName = document.getElementById("alice-name").value.trim();
        const memoryQuestion = document.getElementById("memory-question").value.trim();
        const memoryAnswer = document.getElementById("memory-answer").value.trim();

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

            const resp = await fetch("/api/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    alice_name: aliceName,
                    memory_question: memoryQuestion,
                    memory_answer: memoryAnswer,   // server embeds this, never stores raw
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

            document.getElementById("session-link").textContent = data.link;
            document.getElementById("qr-code").src = data.qr_code;
            UI.showStep("step-waiting");

            // Alice connects SSE to wait for Bob's result
            connectAliceSSE(data.session_id);

        } catch (err) {
            console.error("[session] create failed:", err);
            alert("Something went wrong. Please try again.");
            createBtn.disabled = false;
            createBtn.textContent = "Generate Challenge Link";
        }
    }

    function connectAliceSSE(sessionId) {
        const es = new EventSource(`/api/session/${sessionId}/stream`);

        es.onmessage = async (e) => {
            const event = JSON.parse(e.data);

            if (event.event === "VERIFIED") {
                es.close();
                // Bob passed — we get his pubkey, can now derive shared secret
                const bobPubkey = await Crypto.importPublicKey(event.bob_pubkey_jwk);
                const sharedKey = await Crypto.deriveSharedKey(aliceKeyPair.privateKey, bobPubkey);
                console.log("[session] Shared secret derived — channel open");
                // sharedKey available for future encrypted comms

                document.getElementById("alice-score").textContent = `${event.score}% match ✓`;
                UI.showStep("step-alice-pass");
            }

            if (event.event === "FAILED") {
                es.close();
                document.getElementById("alice-fail-score").textContent = `${event.score}% match`;
                UI.showStep("step-alice-fail");
            }
        };

        es.onerror = () => {
            console.error("[session] SSE connection lost");
        };
    }

    function copyLink() {
        if (!currentLink) return;
        navigator.clipboard.writeText(currentLink)
            .then(() => {
                const btn = document.querySelector(".link-box .btn-secondary");
                if (btn) { btn.textContent = "Copied!"; setTimeout(() => btn.textContent = "Copy", 2000); }
            })
            .catch(() => alert("Copy failed — select the link and copy manually"));
    }

    // ─── Bob ──────────────────────────────────────────────────────────────────

    async function initBob(sessionId) {
        UI.showStep("step-loading");

        // Generate Bob's keypair immediately
        try {
            bobKeyPair = await Crypto.generateKeyPair();
            const keyStatus = document.getElementById("bob-key-status");
            if (keyStatus) {
                keyStatus.innerHTML = '<span style="color:var(--accent)">✓ Your encryption keys are ready</span>';
            }
            const submitBtn = document.getElementById("submit-btn");
            if (submitBtn) submitBtn.disabled = false;
        } catch (err) {
            console.error("[session] Bob key generation failed:", err);
        }

        // Fetch the session to get Alice's question
        try {
            const resp = await fetch(`/api/session/${sessionId}`);
            if (resp.status === 404) {
                UI.showStep("step-expired");
                return;
            }
            const data = await resp.json();
            if (data.phase !== "WAITING_FOR_BOB") {
                UI.showStep("step-expired");
                return;
            }

            document.getElementById("alice-name-display").textContent = data.alice_name;
            document.getElementById("challenge-question").textContent = data.memory_question;
            UI.showStep("step-bob-challenge");

        } catch (err) {
            console.error("[session] initBob fetch failed:", err);
            UI.showStep("step-expired");
        }
    }

    async function submitAnswer() {
        // const sessionId = document.querySelector("[data-session-id]")?.dataset.sessionId;
        const sessionId = SESSION_ID;
        const bobName = document.getElementById("bob-name").value.trim();
        const answer = document.getElementById("bob-answer").value.trim();

        if (!bobName || !answer) {
            alert("Please fill in your name and answer.");
            return;
        }
        if (!bobKeyPair) {
            alert("Keys still generating — please wait.");
            return;
        }

        const submitBtn = document.getElementById("submit-btn");
        submitBtn.disabled = true;
        submitBtn.textContent = "Submitting...";
        UI.showStep("step-scoring");

        try {
            const bobPubkeyJwk = await Crypto.exportPublicKey(bobKeyPair.publicKey);

            const resp = await fetch(`/api/session/${sessionId}/verify`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    bob_name: bobName,
                    answer: answer,
                    bob_pubkey_jwk: bobPubkeyJwk
                })
            });

            const data = await resp.json();

            if (data.result === "PASS") {
                // Alice's pubkey only arrives here — after Bob proved himself
                const alicePubkey = await Crypto.importPublicKey(data.alice_pubkey_jwk);
                const sharedKey = await Crypto.deriveSharedKey(bobKeyPair.privateKey, alicePubkey);
                console.log("[session] Shared secret derived — channel open");
                // sharedKey available for future encrypted comms

                document.getElementById("bob-score").textContent = `${data.score}% match ✓`;
                UI.showStep("step-bob-pass");
            } else {
                document.getElementById("bob-fail-score").textContent = `${data.score}% match`;
                UI.showStep("step-bob-fail");
            }

        } catch (err) {
            console.error("[session] submitAnswer failed:", err);
            alert("Something went wrong. Please try again.");
            UI.showStep("step-bob-challenge");
            submitBtn.disabled = false;
            submitBtn.textContent = "Submit Answer";
        }
    }

    return { initAlice, create, copyLink, initBob, submitAnswer };
})();
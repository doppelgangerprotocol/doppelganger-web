/**
 * embed.js — In-browser embedding via Transformers.js (vanilla JS / ES Module)
 *
 * No npm. No bundler. No build step.
 * Imported directly from CDN as an ES Module.
 *
 * Replaces the embedding microservice entirely.
 * Runs all-MiniLM-L6-v2 quantized (~23MB) via ONNX Runtime WASM.
 * Same model as the server — vectors are fully compatible.
 *
 * Privacy guarantee:
 *   Plaintext never leaves the device. Ever.
 *   The model runs locally, the vector is computed locally,
 *   only the vector is sent to the server.
 *
 * Usage:
 *   const vector = await Embedder.embed("chicken burrito bowl with extra guac");
 *   // → number[] of 384 L2-normalized values
 */

import { pipeline, env } from 'https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2';

// Use browser cache for model weights — 23MB download once, then instant
env.allowRemoteModels = true;
env.useBrowserCache   = true;
env.allowLocalModels  = false;

const MODEL_NAME = "Xenova/all-MiniLM-L6-v2";

let _pipeline   = null;
let _loadPromise = null;
let _ready      = false;

// ── Helpers ──────────────────────────────────────────────────────────────────

function _log(type, title, data) {
    if (typeof ProtocolLog !== "undefined") {
        ProtocolLog.emit(type, title, data);
    }
}

// ── Load ─────────────────────────────────────────────────────────────────────

/**
 * load()
 *
 * Initializes the pipeline. Called automatically on first embed().
 * Safe to call multiple times — returns the same promise if already loading.
 * Call early (on page load) to warm the model while the user fills the form.
 */
async function load() {
    if (_ready) return;
    if (_loadPromise) return _loadPromise;

    _loadPromise = (async () => {
        try {
            _log("embed", "Loading model — first load ~23MB, cached after", {
                model: MODEL_NAME,
                runtime: "ONNX Runtime WASM",
                plaintext_leaves_device: "never"
            });

            _pipeline = await pipeline(
                "feature-extraction",
                MODEL_NAME,
                {
                    progress_callback: (progress) => {
                        if (progress.status === "downloading") {
                            const pct = progress.progress
                                ? `${Math.round(progress.progress)}%`
                                : "...";
                            _log("embed", `Downloading model weights: ${pct}`, {
                                file: progress.file || MODEL_NAME
                            });
                        }
                        if (progress.status === "ready") {
                            _log("embed", "Model ready — inference runs entirely in browser", {
                                model: MODEL_NAME,
                                device: "CPU (WASM)",
                                plaintext_leaves_device: "never"
                            });
                        }
                    }
                }
            );

            _ready = true;
            _log("embed", "Embedder initialized", {
                model: MODEL_NAME,
                dimensions: 384,
                normalization: "L2 — cosine similarity = dot product"
            });

        } catch (err) {
            _loadPromise = null; // allow retry
            _log("embed", "Model load failed", { error: err.message });
            throw err;
        }
    })();

    return _loadPromise;
}

// ── Embed ─────────────────────────────────────────────────────────────────────

/**
 * embed(text)
 *
 * Returns a 384-dimensional L2-normalized number[].
 * Compatible with server-side all-MiniLM-L6-v2 vectors.
 *
 * @param {string} text
 * @returns {Promise<number[]>}
 */
async function embed(text) {
    if (!text?.trim()) throw new Error("Cannot embed empty text");

    if (!_ready) await load();

    _log("embed", "Embedding answer locally", {
        preview: text.slice(0, 40) + (text.length > 40 ? "..." : ""),
        plaintext_leaves_device: "never"
    });

    const start = performance.now();

    const output = await _pipeline(text.trim(), {
        pooling:   "mean",
        normalize: true     // L2 normalize — matches server behavior exactly
    });

    const vector  = Array.from(output.data);
    const elapsed = (performance.now() - start).toFixed(0);

    _log("embed", "Answer embedded in browser", {
        dimensions:      vector.length,
        inference_time:  `${elapsed}ms`,
        "preview [0..7]": vector.slice(0, 8).map(v => v.toFixed(4)),
        server_call:     "none"
    });

    return vector;
}

// ── Similarity ────────────────────────────────────────────────────────────────

/**
 * cosineSimilarity(a, b)
 * Since vectors are L2-normalized, cosine similarity = dot product.
 */
function cosineSimilarity(a, b) {
    if (a.length !== b.length) {
        throw new Error(`Dimension mismatch: ${a.length} vs ${b.length}`);
    }
    return a.reduce((sum, val, i) => sum + val * b[i], 0);
}

/** score(a, b) — returns 0–100 percentage matching server display format */
function score(a, b) {
    return Math.round(cosineSimilarity(a, b) * 100);
}

function isReady() { return _ready; }

// ── Export ────────────────────────────────────────────────────────────────────

window.Embedder = { load, embed, cosineSimilarity, score, isReady };
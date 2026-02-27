/**
 * UI helpers — pure DOM, no protocol logic
 */

const UI = (() => {

    function showStep(stepId) {
        // .screen targets only full-page screens — avoids conflict with
        // .step-item elements in the landing page how-it-works section
        document.querySelectorAll(".screen").forEach(el => {
            el.classList.add("hidden");
            el.classList.remove("fade-in");
        });
        const el = document.getElementById(stepId);
        if (el) {
            el.classList.remove("hidden");
            void el.offsetWidth; // force reflow so fade-in replays every time
            el.classList.add("fade-in");
        }
    }

    // Character counters for Alice's form
    document.addEventListener("DOMContentLoaded", () => {
        const counters = [
            ["memory-question", "q-count"],
            ["memory-answer",   "a-count"]
        ];
        counters.forEach(([textareaId, counterId]) => {
            const textarea = document.getElementById(textareaId);
            const counter  = document.getElementById(counterId);
            if (textarea && counter) {
                textarea.addEventListener("input", () => {
                    counter.textContent = textarea.value.length;
                });
            }
        });
    });

    return { showStep };
})();
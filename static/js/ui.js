/**
 * UI helpers — pure DOM, no protocol logic
 */

const UI = (() => {

    function showStep(stepId) {
        document.querySelectorAll(".step").forEach(el => el.classList.add("hidden"));
        const el = document.getElementById(stepId);
        if (el) {
            el.classList.remove("hidden");
            el.classList.add("fade-in");
        }
    }

    // Character counters
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
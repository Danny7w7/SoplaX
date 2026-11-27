const startButton = document.getElementById("startButton");
const linkContainer = document.getElementById("linkContainer");
const countdown = document.getElementById("countdown");
const countdownValue = document.getElementById("countdownValue");
const linkStatus = document.getElementById("linkStatus");
const urlInput = document.getElementById("copiableInput");
const copyButton = document.getElementById("copyButton");

startButton.addEventListener("click", () => {
    let seconds = 5;
    countdownValue.textContent = seconds;
    startButton.hidden = true;
    countdown.hidden = false;
    countdown.focus();
    linkStatus.textContent = `El enlace aparecerá en ${seconds} segundos.`;

    const timer = setInterval(() => {
        seconds -= 1;
        countdownValue.textContent = seconds;
        if (seconds === 0) {
            clearInterval(timer);
            const focusOnCountdown = document.activeElement === countdown;
            countdown.hidden = true;
            linkContainer.hidden = false;
            if (focusOnCountdown) {
                urlInput.focus();
                urlInput.select();
            }
            linkStatus.textContent = "Enlace listo.";
        }
    }, 1000);
});

copyButton.addEventListener("click", async () => {
    let copied = false;
    try {
        await navigator.clipboard.writeText(urlInput.value);
        copied = true;
    } catch {
        urlInput.focus();
        urlInput.select();
        try {
            copied = document.execCommand("copy");
        } catch {
            copied = false;
        }
        if (copied) {
            copyButton.focus();
        }
    }

    linkStatus.textContent = copied ? "Enlace copiado." : "El enlace está seleccionado. Cópialo manualmente.";
});

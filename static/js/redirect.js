const startButton = document.getElementById("startButton");
const linkContainer = document.getElementById("linkContainer");
const countdown = document.getElementById("countdown");
const urlInput = document.getElementById("copiableInput");
const copyButton = document.getElementById("copyButton");
const copyStatus = document.getElementById("copyStatus");

startButton.addEventListener("click", () => {
    let seconds = 5;
    countdown.textContent = `Enlace disponible en ${seconds} s`;
    countdown.hidden = false;
    startButton.hidden = true;
    countdown.focus();

    const timer = setInterval(() => {
        seconds -= 1;
        if (seconds === 0) {
            clearInterval(timer);
            const focusOnCountdown = document.activeElement === countdown;
            countdown.hidden = true;
            linkContainer.hidden = false;
            if (focusOnCountdown) {
                urlInput.focus();
            }
            return;
        }
        countdown.textContent = `Enlace disponible en ${seconds} s`;
    }, 1000);
});

copyButton.addEventListener("click", async () => {
    let copied;
    try {
        await navigator.clipboard.writeText(urlInput.value);
        copied = true;
    } catch {
        urlInput.select();
        try {
            copied = document.execCommand("copy");
        } catch {
            copied = false;
        }
    }

    copyStatus.textContent = copied ? "Enlace copiado." : "Selecciona y copia el enlace manualmente.";
});

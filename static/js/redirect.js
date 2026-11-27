const startButton = document.getElementById("startButton");
const linkContainer = document.getElementById("linkContainer");
const countdown = document.getElementById("countdown");
const countdownValue = document.getElementById("countdownValue");
const linkStatus = document.getElementById("linkStatus");
const urlInput = document.getElementById("copiableInput");

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
            countdown.hidden = true;
            linkContainer.hidden = false;
            linkStatus.textContent = "Enlace listo.";
            urlInput.focus();
            urlInput.select();
        }
    }, 1000);
});

document.getElementById("copyButton").addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(urlInput.value);
    } catch {
        urlInput.select();
        document.execCommand("copy");
    }
    linkStatus.textContent = "Enlace copiado.";
});

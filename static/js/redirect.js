const startButton = document.getElementById("startButton");
const linkContainer = document.getElementById("linkContainer");
const countdown = document.getElementById("countdown");
const urlInput = document.getElementById("copiableInput");

startButton.addEventListener("click", () => {
    let seconds = 5;
    countdown.textContent = seconds;
    startButton.style.display = "none";

    const timer = setInterval(() => {
        seconds -= 1;
        countdown.textContent = seconds;
        if (seconds === 0) {
            clearInterval(timer);
            countdown.style.display = "none";
            linkContainer.style.display = "block";
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
});

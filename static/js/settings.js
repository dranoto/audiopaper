// settings.js - Settings page functionality (voice sample playback)

function initSettingsPage() {
    let currentAudio = null;
    const playIconClass = 'bi bi-volume-up-fill';
    const stopIconClass = 'bi bi-stop-circle-fill';
    const loadingIconClass = 'spinner-border spinner-border-sm';

    function stopCurrentSample() {
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
        }
        const previousButton = document.querySelector('.playing');
        if (previousButton) {
            resetButtonState(previousButton);
        }
        currentAudio = null;
    }

    function resetButtonState(button) {
        button.classList.remove('playing');
        button.querySelector('i').className = playIconClass;
        button.disabled = false;
    }

    function playSample(button, voice) {
        const icon = button.querySelector('i');
        icon.className = loadingIconClass;
        button.disabled = true;

        fetch('/play_voice_sample', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voice: voice }),
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            currentAudio = new Audio(data.audio_url);
            button.classList.add('playing');
            icon.className = stopIconClass;
            button.disabled = false;

            currentAudio.play();

            currentAudio.addEventListener('ended', () => {
                resetButtonState(button);
                currentAudio = null;
            });
        })
        .catch(error => {
            console.error('Error playing voice sample:', error);
            alert('Failed to play voice sample. See console for details.');
            resetButtonState(button);
        });
    }

    const playButtons = document.querySelectorAll('.play-sample-button');
    playButtons.forEach(button => {
        button.addEventListener('click', () => {
            const wasPlaying = button.classList.contains('playing');

            stopCurrentSample();

            if (!wasPlaying) {
                const targetId = button.dataset.targetSelect;
                const select = document.getElementById(targetId);
                const voice = select.value;
                playSample(button, voice);
            }
        });
    });
}

// Expose to window
window.initSettingsPage = initSettingsPage;

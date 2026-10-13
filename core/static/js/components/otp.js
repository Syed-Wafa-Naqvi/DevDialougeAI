/* ==========================================================================
   DevDialogue AI — OTP Digit Input Handler (§4.1)
   Auto-advance, paste support ("123456" fills all), backspace moves back, countdown
   ========================================================================== */

export function setupOTPController(containerId, onComplete, countdownSeconds = 45) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const inputs = Array.from(container.querySelectorAll('.otp-digit-input'));
    if (inputs.length === 0) return;

    inputs.forEach((input, index) => {
        input.addEventListener('input', (e) => {
            const val = e.target.value;
            if (val.length > 0) {
                // Focus next input if available
                if (index < inputs.length - 1) {
                    inputs[index + 1].focus();
                }
            }

            checkCompletion();
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !input.value && index > 0) {
                inputs[index - 1].focus();
            }
        });

        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const pastedText = (e.clipboardData || window.clipboardData).getData('text').trim();
            if (/^\d+$/.test(pastedText)) {
                const digits = pastedText.split('');
                inputs.forEach((inp, idx) => {
                    if (digits[idx]) {
                        inp.value = digits[idx];
                    }
                });
                inputs[Math.min(digits.length, inputs.length) - 1].focus();
                checkCompletion();
            }
        });
    });

    function checkCompletion() {
        const otpCode = inputs.map(i => i.value).join('');
        if (otpCode.length === inputs.length && onComplete) {
            onComplete(otpCode);
        }
    }

    // Countdown Timer logic for Resend button (§4.1)
    const resendBtn = document.getElementById('btn-resend-otp');
    const timerSpan = document.getElementById('otp-countdown-timer');

    if (resendBtn && timerSpan) {
        let remaining = countdownSeconds;
        resendBtn.setAttribute('disabled', 'true');

        const interval = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) {
                clearInterval(interval);
                resendBtn.removeAttribute('disabled');
                timerSpan.textContent = '';
            } else {
                const mins = Math.floor(remaining / 60);
                const secs = remaining % 60;
                timerSpan.textContent = `(${mins}:${secs < 10 ? '0' : ''}${secs})`;
            }
        }, 1000);
    }
}

// DevDialogue AI Javascript Entry
document.addEventListener('DOMContentLoaded', () => {
    console.log('DevDialogue AI Static Assets Loaded.');
    
    // Auto fadeout alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s ease';
            alert.style.opacity = '0';
            setTimeout(() => {
                alert.remove();
            }, 500);
        }, 5000);
    });
});

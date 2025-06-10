// static/js/main.js
console.log("main.js loaded successfully!");

// Функция для отображения flash-сообщений (если вы захотите делать это через JS)
function showFlash(message, category = 'info') {
    const flashContainer = document.querySelector('.container.mt-4'); // Или более специфичный селектор
    if (!flashContainer) return;

    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${category} alert-dismissible fade show`;
    alertDiv.setAttribute('role', 'alert');
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="close" data-dismiss="alert" aria-label="Close">
            <span aria-hidden="true">&times;</span>
        </button>
    `;
    // Вставляем сообщение перед первым дочерним элементом контейнера (или в конец)
    if (flashContainer.firstChild) {
        flashContainer.insertBefore(alertDiv, flashContainer.firstChild);
    } else {
        flashContainer.appendChild(alertDiv);
    }

    // Автоматическое скрытие через 5 секунд
    setTimeout(() => {
        // Используем Bootstrap JS для плавного закрытия, если он доступен
        if (window.bootstrap && window.bootstrap.Alert) {
             const alertInstance = window.bootstrap.Alert.getInstance(alertDiv) || new window.bootstrap.Alert(alertDiv);
             alertInstance.close();
        } else if (window.jQuery && $.fn.alert) { // Fallback for Bootstrap 4 jQuery plugin
            $(alertDiv).alert('close');
        }
        else {
            alertDiv.remove();
        }
    }, 5000);
}

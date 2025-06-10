// static/js/habits.js
document.addEventListener('DOMContentLoaded', function () {
    const container = document.querySelector('.container[data-create-habit-url]'); // Главный контейнер с data-атрибутами
    if (!container) {
        console.error('Container with data URLs for habits not found.');
        return;
    }

    const createHabitUrl = container.dataset.createHabitUrl;
    const updateHabitEntryUrlTemplate = container.dataset.updateHabitEntryUrlTemplate;
    const deleteHabitUrlTemplate = container.dataset.deleteHabitUrlTemplate;
    const csrfToken = container.dataset.csrfToken;

    // Сохранение новой привычки
    const saveNewHabitBtn = document.getElementById('saveNewHabitBtn');
    if (saveNewHabitBtn) {
        saveNewHabitBtn.addEventListener('click', function () {
            const form = document.getElementById('addHabitForm');
            const name = form.querySelector('[name="name"]').value;
            const description = form.querySelector('[name="description"]').value;
            const formation_target_days = form.querySelector('[name="formation_target_days"]').value;
            const frequency_type = form.querySelector('[name="frequency_type"]').value;
            
            let days_of_week = null;
            let days_of_month = null;

            if (!name.trim()) {
                alert('Название привычки не может быть пустым.');
                return;
            }

            if (frequency_type === 'WEEKLY') {
                days_of_week = Array.from(form.querySelectorAll('input[name="days_of_week"]:checked'))
                                    .map(cb => parseInt(cb.value));
                if (days_of_week.length === 0) {
                    alert('Для еженедельной привычки выберите хотя бы один день недели.');
                    return;
                }
            } else if (frequency_type === 'MONTHLY') {
                const daysOfMonthStr = form.querySelector('input[name="days_of_month_str"]').value;
                days_of_month = daysOfMonthStr.split(',')
                                    .map(s => parseInt(s.trim()))
                                    .filter(n => !isNaN(n) && n >= 1 && n <= 31);
                if (days_of_month.length === 0) {
                    alert('Для ежемесячной привычки укажите хотя бы один день месяца (числа от 1 до 31 через запятую).');
                    return;
                }
            }

            fetch(createHabitUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ name, description, formation_target_days, frequency_type, days_of_week, days_of_month })
            })
            .then(response => response.json())
            .then(data => {
                if (data.habit) {
                    $('#addHabitModal').modal('hide');
                    // Вместо alert, можно использовать вашу функцию showFlash, если она доступна глобально
                    // или перезагрузить страницу для простоты
                    // showFlash('Привычка "' + data.habit.name + '" успешно добавлена!', 'success');
                    window.location.reload(); 
                } else {
                    alert(data.error || 'Не удалось создать привычку.');
                }
            })
            .catch(error => {
                console.error('Ошибка создания привычки:', error);
                alert('Произошла ошибка при создании привычки.');
            });
        });
    }

    // Обновление статуса выполнения привычки и заметок
    document.querySelectorAll('.daily-habit-checkbox, .habit-notes').forEach(element => {
        element.addEventListener('change', function (event) {
            const entryId = this.classList.contains('daily-habit-checkbox') ? this.value : this.dataset.entryId;
            const isCompleted = document.getElementById(`habitCheck_${entryId}`).checked;
            const notes = document.querySelector(`.habit-notes[data-entry-id="${entryId}"]`).value;
            const habitId = document.getElementById(`habitCheck_${entryId}`).dataset.habitId;

            const updateUrl = updateHabitEntryUrlTemplate.replace('0', entryId);

            fetch(updateUrl, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ is_completed: isCompleted, notes: notes })
            })
            .then(response => response.json())
            .then(data => {
                if (data.message) {
                    // Обновляем UI для стрика и прогресс-бара
                    const streakElement = document.getElementById(`streak-${habitId}`);
                    if (streakElement) {
                        streakElement.textContent = data.habit_streak;
                    }
                    const progressBar = document.querySelector(`.progress-bar[aria-valuenow][aria-valuemax][style*="width"]`);
                    // Это более сложная часть для обновления прогресс-бара, так как он зависит от target.
                    // Проще перезагрузить страницу или передавать target_days в ответе.
                    // Для простоты, можно просто показать сообщение.
                    // showFlash(data.message, 'success');
                    if (data.habit_is_active === false) { // Если привычка стала неактивной (сформирована)
                        window.location.reload(); // Перезагружаем, чтобы она переместилась в "Сформированные"
                    }
                } else if (data.error) {
                    // showFlash(data.error, 'danger');
                    alert(data.error);
                }
            })
            .catch(error => {
                console.error('Ошибка обновления привычки:', error);
                // showFlash('Ошибка при обновлении привычки.', 'danger');
                alert('Ошибка при обновлении привычки.');
            });
        });
    });

    // Удаление привычки
    document.querySelectorAll('.delete-habit-btn').forEach(button => {
        button.addEventListener('click', function () {
            const habitId = this.dataset.habitId;
            const habitName = this.dataset.habitName;
            if (!confirm(`Вы уверены, что хотите удалить привычку "${habitName}" и все связанные с ней записи?`)) {
                return;
            }

            const deleteUrl = deleteHabitUrlTemplate.replace('0', habitId);

            fetch(deleteUrl, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.message) {
                    // showFlash(data.message, 'info');
                    window.location.reload(); // Перезагружаем страницу для обновления списка
                } else if (data.error) {
                    // showFlash(data.error, 'danger');
                    alert(data.error);
                }
            })
            .catch(error => {
                console.error('Ошибка удаления привычки:', error);
                // showFlash('Ошибка при удалении привычки.', 'danger');
                alert('Ошибка при удалении привычки.');
            });
        });
    });

    // Вспомогательная функция для отображения flash-сообщений (если она у вас есть в main.js)
    // function showFlash(message, category) {
    //     // Ваша реализация отображения flash-сообщений
    //     // Например, создание div.alert и добавление его в DOM
    //     console.log(`FLASH (${category}): ${message}`);
    //     alert(`${category.toUpperCase()}: ${message}`); // Простой alert для примера
    // }
});

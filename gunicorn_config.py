import multiprocessing

# Таймаут для обробки запитів (300 секунд = 5 хвилин)
timeout = 300

# Кількість робочих процесів, для безкоштовного плану краще встановити 1
workers = 1

# Кількість потоків в кожному процесі
threads = 2

# Перезапуск процесу після обробки певної кількості запитів
max_requests = 5
max_requests_jitter = 2

# Лог-рівень
loglevel = "info"

# Очищати середовище після обробки запитів
preload_app = False

# Обмеження на розмір запиту (64MB)
limit_request_line = 0
limit_request_fields = 32768
limit_request_field_size = 0

# Worker класс для асинхронної обробки
worker_class = "sync"

# Збільшений keepalive для довгих запитів
keepalive = 65

# Час очікування перед видачею SIGKILL для worker'а (повинен бути більше timeout)
graceful_timeout = 360

# Рівень пріоритету процесу (нижчий рівень = більше ресурсів)
worker_priority = 10

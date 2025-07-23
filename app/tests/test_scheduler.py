import pytest
import asyncio
from unittest.mock import AsyncMock
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Импортируем сам планировщик
from bot import scheduler

@pytest.mark.asyncio
async def test_scheduler_runs_check_sub():
    mock_check_subscriptions = AsyncMock()

    # Добавляем мок-функцию вместо check_subscriptions
    scheduler.add_job(
        mock_check_subscriptions,
        IntervalTrigger(seconds=1),  # Уменьшаем интервал
        id="test_check_subscriptions",
        replace_existing=True
    )

    # Запускаем планировщик
    scheduler.start()

    # Даем время планировщику сработать
    await asyncio.sleep(3)

    # Проверяем, что функция вызвалась хотя бы раз
    mock_check_subscriptions.assert_called()

    # Останавливаем планировщик после теста
    scheduler.shutdown()
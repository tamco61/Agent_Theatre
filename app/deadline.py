"""Общий срок запроса в главном потоке Unix, поверх сетевых idle timeout."""

from collections.abc import Callable
import signal
import threading
from typing import TypeVar


T = TypeVar("T")


def with_deadline(call: Callable[[], T], seconds: float) -> T:
    # В других потоках/на Windows остаётся timeout самого API-клиента.
    # Уже установленный таймер приложения не переопределяем.
    if (threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL)[0] > 0):
        return call()
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise TimeoutError("Превышен общий срок ожидания API")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

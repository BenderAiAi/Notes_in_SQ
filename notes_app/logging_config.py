from __future__ import annotations

import logging
import sys

try:
    from colorama import Fore, Style, just_fix_windows_console
except ImportError:  # Приложение продолжит работать без цветов.
    class _EmptyColors:
        def __getattr__(self, _name: str) -> str:
            return ""

    Fore = Style = _EmptyColors()

    def just_fix_windows_console() -> None:
        return None


class ConsoleFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%H:%M:%S")
        color = self.COLORS.get(record.levelno, "")
        level = {
            logging.DEBUG: "ОТЛАДКА",
            logging.INFO: "ГОТОВО",
            logging.WARNING: "ВНИМАНИЕ",
            logging.ERROR: "ОШИБКА",
            logging.CRITICAL: "СБОЙ",
        }.get(record.levelno, record.levelname)
        return f"{Fore.LIGHTBLACK_EX}{timestamp}{Style.RESET_ALL}  {color}{level:<8}{Style.RESET_ALL}  {record.getMessage()}"


def configure_logging(debug: bool = False) -> logging.Logger:
    just_fix_windows_console()
    logger = logging.getLogger("noteflow")
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ConsoleFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    return logger


def print_banner(version: str, url: str, settings: dict[str, str]) -> None:
    width = 66
    source = settings.get("source_dir") or "не выбрана"
    output = settings.get("output_dir") or "не выбрана"
    lines = [
        f"NoteFlow  ·  версия {version}",
        "Локальный сервис запущен и готов к работе",
        "",
        f"Открыть интерфейс:  {url}",
        f"Исходные отчёты:   {source}",
        f"Готовые файлы:     {output}",
        "",
        "Для остановки нажмите Ctrl+C",
    ]
    border = "─" * width
    print(f"\n{Fore.CYAN}┌{border}┐{Style.RESET_ALL}")
    for line in lines:
        clipped = line if len(line) <= width - 2 else "…" + line[-(width - 3):]
        print(f"{Fore.CYAN}│{Style.RESET_ALL} {clipped:<{width - 1}}{Fore.CYAN}│{Style.RESET_ALL}")
    print(f"{Fore.CYAN}└{border}┘{Style.RESET_ALL}\n")

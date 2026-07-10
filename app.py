from __future__ import annotations

import argparse
import threading
import webbrowser

from notes_app import __version__
from notes_app.config import load_settings
from notes_app.logging_config import configure_logging, print_banner
from notes_app.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="NoteFlow — подготовка Note trades SQ")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=17843, type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--debug", action="store_true")
    arguments = parser.parse_args()
    url = f"http://{arguments.host}:{arguments.port}"
    configure_logging(arguments.debug)
    print_banner(__version__, url, load_settings())
    if not arguments.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    create_app().run(
        host=arguments.host,
        port=arguments.port,
        debug=arguments.debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nNoteFlow остановлен. Окно можно закрыть.\n")

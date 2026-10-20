from __future__ import annotations

import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from .app import App

    App().run()


if __name__ == "__main__":
    main()

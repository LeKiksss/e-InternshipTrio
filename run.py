import os

from app import create_app


app = create_app()


def _port():
    raw_value = os.getenv("APP_PORT", os.getenv("PORT", "5000"))
    try:
        port = int(raw_value)
    except ValueError as error:
        raise SystemExit("APP_PORT or PORT must be a valid integer.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("APP_PORT or PORT must be between 1 and 65535.")
    return port


if __name__ == "__main__":
    app.run(
        host=os.getenv("APP_HOST", os.getenv("HOST", "127.0.0.1")),
        port=_port(),
        debug=False,
    )

from precedent.api import app
from precedent.settings import get_settings


def main() -> None:
    import os

    import uvicorn

    s = get_settings()
    port = int(os.environ.get("PORT", s.port))
    uvicorn.run("precedent.api:app", host="0.0.0.0", port=port, factory=False)


if __name__ == "__main__":
    main()

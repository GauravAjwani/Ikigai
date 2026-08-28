from ikigai.api import app
from ikigai.settings import get_settings


def main() -> None:
    import os

    import uvicorn

    s = get_settings()
    port = int(os.environ.get("PORT", s.port))
    uvicorn.run("ikigai.api:app", host="0.0.0.0", port=port, factory=False)


if __name__ == "__main__":
    main()

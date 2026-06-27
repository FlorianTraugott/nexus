"""Package entrypoint so `python -m app.mcp` runs the stdio server."""

from app.mcp.server import main

if __name__ == "__main__":
    main()

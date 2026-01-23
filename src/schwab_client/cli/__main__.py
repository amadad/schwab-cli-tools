"""Allow running the CLI as a module: python -m src.schwab_client.cli"""

from . import main

if __name__ == "__main__":
    main()

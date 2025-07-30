# ZPLWeb

Desktop agent that listens to a remote socket.io service and prints ZPL labels using the configured printer. Built with PySide6.

## Development

Run the application:

```bash
python -m ZPLWeb.main
```

Build a single executable with PyInstaller:

```bash
pyinstaller ZPLWeb.spec
```

## Tests

```bash
pytest
```


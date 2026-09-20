# Contributing

Thank you for helping improve Oni Thermal LCD Control.

## Development workflow

1. Use Python 3.12 on Windows and install the project with `py -3.12 -m pip install -e ".[gui]"`.
2. Keep changes focused. Do not redesign the approved interface or alter USB/device behavior as part of unrelated work.
3. Never commit captures, logs, local media, profiles, credentials, machine-specific allowlists, or generated build output.
4. Add or update tests for behavior changes without weakening existing assertions.
5. Run the complete validation before submitting a change:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m unittest discover -s tests -q
py -3.12 -m pytest -q
py -3.12 tools\ui_lock.py check
```

## Device and transport safety

Changes that can send USB traffic require reproducible capture evidence, bounded resource use, strict device identity checks, and explicit authorization. Never bypass or broaden a safety gate to make a device appear supported. Remove personal hardware identifiers before sharing evidence.

## Pull requests

Describe the problem, the smallest implemented solution, test results, and any hardware used. Include screenshots for an explicitly approved visual change. Do not record a new UI-lock baseline unless the visual change has been reviewed and accepted.

By contributing, you agree that your contribution is licensed under the MIT License.

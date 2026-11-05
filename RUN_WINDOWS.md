# Windows 11 — Run & Troubleshoot

## Recommended
1. Install Python 3.10+ and Node.js LTS.
2. Extract the ZIP directly into a short local folder (for example `C:\EkoSBI` or `D:\EkoSBI`). The ZIP has no extra wrapper folder. Avoid running from inside the ZIP viewer.
3. Double-click `start.bat`.
4. On first run, allow it to create a short-path Python environment at `%LOCALAPPDATA%\EkoSBI\venv_v62_6_109` and install packages.
5. Open `http://127.0.0.1:5173`.

## If npm installation fails
Open Command Prompt in `frontend` and run:

```cmd
npm cache verify
npm install --no-audit --no-fund
npm run build
```

If your network uses a corporate proxy, configure npm's proxy/registry first. The project intentionally does not ship `node_modules`; it is platform-specific and should be installed on the target Windows machine.

## Backend check
In a second Command Prompt:

```cmd
cd backend
"%LOCALAPPDATA%\EkoSBI\venv_v62_6_109\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/docs`.

## Frontend check

```cmd
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

The browser should show the EKO × SBI Revenue Reconciliation dashboard.

## Important
The Python virtual environment is intentionally stored in `%LOCALAPPDATA%\EkoSBI\venv_v62_6_109` to avoid Windows path-length failures during NumPy installation. Expected commission remains backend-controlled and rule-driven.

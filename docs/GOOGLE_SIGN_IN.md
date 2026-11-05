# Google sign-in: set-up and check

1. Create the Web client in Google Cloud Console with JS origin `http://127.0.0.1:5173` and redirect URI `http://127.0.0.1:8000/api/auth/oidc/callback`.
2. Put the Client ID and secret into `backend\.env` (run `setup_google_login.bat`, it asks for both and writes the four `OIDC_` lines). Restart with `start.bat`.
3. The person who will sign in must exist in the app (`python create_platform_admin.py --email name@eko.co.in --role operator`). Google only proves who they are; the app still decides who may enter.
4. Check the set-up (the app must be running), from the `backend` folder:
   `python check_google_login.py --email name@eko.co.in`
   It prints PASS / FAIL for the settings, the Google button, Google accepting the client and the user existing. It never prints the secret.
5. Last step, only that person can do it: open the app, press **Continue with Google** and sign in with the work account.

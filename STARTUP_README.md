# Fast and reliable launcher

Double-click `start.bat`. On the first run it creates the Python virtual environment and installs backend/frontend dependencies. Later runs skip those steps and start the services directly.

If startup fails, keep the two service CMD windows open and inspect the first error shown there.


## Fresh-session startup control

Every `start.bat` launch clears prior uploaded source files, reconciliation cache and prior run log. This is intentional: the dashboard must open empty and must never display a previous month's reconciliation. Upload the current Transaction, Commission and approved Rate/Slab Master files, validate all three, and then click **Run Reconciliation**. Reconciliation is not auto-started after upload.

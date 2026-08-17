# Setting Up Google Cloud Vision (GCV) for Step 2

Step 2 (`02_ocr_extract.py`) escalates to Google Cloud Vision when Tesseract's
confidence is too low (e.g. handwritten material). Without credentials
configured, escalation fails with:

```
Your default credentials were not found. To set up Application Default
Credentials, see https://cloud.google.com/docs/authentication/external/set-up-adc
```

This guide walks through fixing that, using the Google Cloud Console
(https://console.cloud.google.com).

## How this project authenticates

`GoogleCloudVisionOCR` in `02_ocr_extract.py` calls `vision.ImageAnnotatorClient()`
with no arguments — it relies entirely on **Application Default Credentials
(ADC)**, which the client library resolves in this order:

1. The `GOOGLE_APPLICATION_CREDENTIALS` environment variable (path to a
   service account JSON key)
2. Credentials from `gcloud auth application-default login`
3. The metadata server (only applies when running *on* Google Cloud, e.g. a
   Compute Engine VM — not relevant on a laptop)

For a local batch pipeline like this one, **option 1 (a service account JSON
key) is the right fit** — it's portable, doesn't depend on a personal Google
login being active, and is what these steps set up.

> Note: `.env.example` in this project lists `GOOGLE_CLOUD_API_KEY`, but
> nothing in the code reads it — the Vision client only ever uses ADC as
> described above, and `.env` is never loaded automatically (no script calls
> `load_dotenv()`, despite `python-dotenv` being in `requirements.txt`).
> Ignore `GOOGLE_CLOUD_API_KEY`; use `GOOGLE_APPLICATION_CREDENTIALS` as
> described below instead.

## Step 1: Create or select a Google Cloud project

1. Go to the [project selector](https://console.cloud.google.com/projectselector2/home/dashboard)
   in the Cloud Console.
2. Either pick an existing project or click **New Project** and create one
   (e.g. `ocr-pipeline`).
3. Note the **Project ID** shown on the dashboard — you'll want it handy for
   the next steps.

## Step 2: Enable billing

The Vision API requires an active billing account on the project, even
though it has a free monthly usage tier.

1. In the Console, go to **Billing** (left sidebar, or search "Billing" in
   the top search bar).
2. If the project isn't linked to a billing account yet, link one (or create
   one if you don't have one).
3. Check current Vision API pricing and the free tier at
   https://cloud.google.com/vision/pricing before proceeding, so you know
   what usage is free vs. billed.

## Step 3: Enable the Cloud Vision API

1. Go to the [Vision API enablement page](https://console.cloud.google.com/apis/enableflow?apiid=vision.googleapis.com)
   (make sure your correct project is selected in the top project switcher
   first).
2. Click **Enable**.

## Step 4: Create a service account

1. In the Console, navigate to **IAM & Admin → Service Accounts** (or search
   "Service Accounts" in the top search bar).
2. Confirm the correct project is selected.
3. Click **Create Service Account**.
4. Give it a name (e.g. `ocr-pipeline-vision`) — the Console will generate an
   email-style ID for it.
5. Click **Create and Continue**.
6. **Role**: for this project's usage (sending image bytes directly to
   `document_text_detection`, not referencing files already in Cloud
   Storage), Vision API access doesn't require a specific predefined IAM
   role beyond the service account existing in a project with the API
   enabled and billing active. You can leave the role step blank/skip it.
   If you want to assign one anyway for clarity/least-privilege in your
   org's IAM policy, look for a Vision-related predefined role in the role
   picker — availability of a dedicated "Cloud Vision" role has varied
   across projects, so check what your project's role list actually offers
   rather than assuming a specific name.
7. Click **Continue**, then **Done**.

## Step 5: Create and download a JSON key

1. From the **Service Accounts** list, click the email address of the
   service account you just created.
2. Open the **Keys** tab.
3. Click **Add Key → Create new key**.
4. Choose **JSON**, then click **Create**.
5. A `.json` file downloads automatically to your browser's default download
   location. **This is the only time you can download this exact key** — if
   you lose it, you'll need to create a new one.

## Step 6: Store the key and point the pipeline at it

1. Move the downloaded JSON file somewhere sensible — **not** inside this
   git repo (to avoid ever accidentally committing it). For example:
   ```bash
   mkdir -p ~/.gcp-keys
   mv ~/Downloads/ocr-pipeline-*.json ~/.gcp-keys/ocr-pipeline-vision.json
   chmod 600 ~/.gcp-keys/ocr-pipeline-vision.json
   ```
2. Set `GOOGLE_APPLICATION_CREDENTIALS` to that path before running the
   pipeline:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp-keys/ocr-pipeline-vision.json
   ```
   Add this line to your shell profile (`~/.zshrc` on macOS) if you want it
   set automatically in every new terminal, rather than re-exporting it each
   session.
3. **If you're launching the GUI** (`gui.py`): the environment variable must
   be set in the *shell you launch the GUI from*, since the GUI's `QProcess`
   calls inherit their environment from the GUI process itself. Export it
   first, then launch `gui.py` from that same terminal session.

## Step 7: Verify it works

With `GOOGLE_APPLICATION_CREDENTIALS` set, test directly against a single
image before running a full batch:

```bash
cd "ocr-pipeline-modular"
python 02_ocr_extract.py --input prep_output/<some_file>.jpg \
  --output-dir /tmp/gcv_test --engine gcv --verbose
```

- **Success** looks like a normal run with `"engine": "gcv"` in the output
  JSON and no `ERROR` lines.
- If you still see `Your default credentials were not found`, double-check:
  - `echo $GOOGLE_APPLICATION_CREDENTIALS` actually prints the path (not
    empty) *in the same terminal/session running the pipeline*
  - The path is correct and the file exists (`ls -la $GOOGLE_APPLICATION_CREDENTIALS`)
- If you see a permission or "API not enabled" error instead, confirm Step 3
  (API enabled) and Step 2 (billing linked) were done on the **same project**
  the service account in Step 4 belongs to — a mismatched project is the
  most common cause of this class of error.

Once verified, switch the Engine setting (CLI `--engine auto`, or the GUI's
Engine dropdown) back to **`auto`** for normal runs, so Tesseract still
handles the easy cases locally and free, escalating to GCV only when needed.

## Security notes

- Never commit the service account JSON key to git. This repo's
  `.gitignore` already ignores `.env`, but the key file itself should simply
  never be placed inside the repo directory at all (per Step 6 above).
- Treat the key like a password — anyone with it can make Vision API calls
  billed to your project.
- To revoke it later: **IAM & Admin → Service Accounts → (your service
  account) → Keys tab → delete the key**, or delete the whole service
  account if it's no longer needed.

# Genome to Medicine — standalone site

A self-contained static site: an interactive explainer of the genomics-powered
drug discovery value chain. This folder is designed to deploy as its **own
separate Vercel project**, independent of the Genetic Report Extractor app.

There is no build step — it is a single static `index.html`.

## Deploy as a separate Vercel project

1. Go to <https://vercel.com/new> and **Import** this Git repository.
2. In the project setup, set **Root Directory** to `site`.
   (This is what makes it a *separate* project from the Python app at the repo
   root — Vercel only looks inside `site/`.)
3. **Framework Preset:** `Other` (no build command needed — it is static).
4. Set the project's **Production Branch** to the branch that contains this
   folder (`claude/drug-discovery-genomics-chain-8h381d`) under
   *Settings → Git*, or merge the folder into your default branch first.
5. Click **Deploy**.

You'll get a fresh URL such as `https://<your-project-name>.vercel.app`,
completely separate from the report-extractor deployment.

## Local preview

```bash
cd site
python3 -m http.server 8000
# open http://localhost:8000
```

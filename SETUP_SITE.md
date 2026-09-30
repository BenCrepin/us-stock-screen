# Publishing the daily page outside work (GitHub Pages)

The daily job already writes the finished page to `docs/index.html`. Once this folder is a
git repository with a remote on a **personal** GitHub account, the same job commits and pushes
it every morning and GitHub Pages serves it at a link you can share with anyone.

Nothing here touches a Claude account or the IOHK organisation. Watchlists on the GitHub Pages
copy are saved in each visitor's own browser.

## One-time setup (about two minutes)

1. Make sure the GitHub CLI is signed in to your **personal** account, not a work one:

```bash
gh auth status
```

   If it shows the wrong account: `gh auth login` and pick the personal one.

2. From this folder, create the repository and push. Pages on a free personal account needs a
   public repository, so the report will be readable by anyone with the link:

```bash
git init -b main
```

```bash
git add .
```

```bash
git commit -m "US stock screen: rules, pipeline and first archive"
```

```bash
gh repo create us-stock-screen --public --source . --push
```

3. Turn on Pages, serving from the `docs` folder on `main`:

```bash
gh api -X POST repos/{owner}/us-stock-screen/pages -f "source[branch]=main" -f "source[path]=/docs"
```

   The page appears within a minute or two at `https://<your-github-user>.github.io/us-stock-screen/`.

4. Test the whole loop once:

```bash
python run_daily.py --no-refresh
```

   The log should end with `site published to GitHub Pages`.

## What gets published

| Path | Contents |
|---|---|
| `docs/index.html` | The latest page: qualifying shares, monitoring list, watchlists |
| `docs/qualifying.csv`, `docs/monitoring.csv` | Raw values for the latest close |
| `docs/report.md` | Markdown version |
| `archive/YYYY-MM-DD/` | Every previous run, browsable in the repository |

Logs and Python caches are excluded by `.gitignore`.

## If you would rather keep it private

A private repository on a free account cannot serve Pages. Options: share the OneDrive link to
`archive/latest/report.html` instead, or use a personal Claude account to publish the page as a
claude.ai artifact (private by default, with cross-device watchlists). The latter has to be done
from a session signed in to that personal account.

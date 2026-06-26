# Resume Agent

A Google ADK multi-agent pipeline that tailors your resume to a job description
using your Excel skill/course/project data.

## Pipeline

```
root_agent
└── resume_pipeline_agent (SequentialAgent)
    ├── jd_analyzer_agent      → parses JD into structured requirements
    ├── retriever_agent        → reads your Excel and selects relevant content
    ├── resume_writer_agent    → drafts the tailored resume
    ├── critic_agent           → critiques for ATS coverage and quality
    └── final_writer_agent     → revises and saves the final resume
```

## Setup

### Prerequisites

- Python 3.11 or newer
- Git installed
- A GitHub account (optional, for pushing the repo)

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. Install dependencies

Option 1: Install from the editable package

```bash
pip install -e .
```

Option 2: Install from requirements.txt

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
copy .env.example .env
# On macOS/Linux use: cp .env.example .env
```

Edit `.env` and add your `GOOGLE_API_KEY`.

Get a free API key at https://aistudio.google.com

### 4. Add your Excel file

Place your `.xlsx` file in this directory, or set `RESUME_EXCEL_PATH` in `.env`.

Your workbook should have sheets named (case-insensitive):
- **Skills** — columns: Category, Skill
- **Courses** — columns: Semester, Course Code, Course Name, Grade, Category, Skill
- **Projects** — columns: Project Title, Description, Skills

### 5. Run the agent

```bash
adk run resume_agent
```

Then paste a job description when prompted. The agent will:
1. Parse the JD
2. Read your Excel sheets
3. Select and rank relevant content
4. Draft a tailored resume
5. Critique and revise it
6. Save the final resume to `output/resume_<role>.md` and `output/resume_<role>.pdf`

## GitHub setup

If you want to push this project to GitHub:

```bash
git init
git add .
git commit -m "Initial commit"
```

Create the repo on GitHub, then add the remote and push:

```bash
git remote add origin https://github.com/<your-username>/<repo>.git
git branch -M main
git push -u origin main
```

Or use GitHub CLI if installed:

```bash
gh repo create <repo-name> --public --source=. --remote=origin --push
```

> Do not commit `.env` or the `.venv/` directory. These are already excluded by `.gitignore`.

## Output

- `output/resume_<role>.md` — your tailored resume in Markdown
- `output/resume_<role>.pdf` — your tailored resume as a rendered PDF
- `output/pipeline_log.json` — full JSON log of each pipeline step (useful for debugging)

## Tips

- The more detailed your project descriptions in the Excel file, the better the bullets
- Run with `RESUME_MODEL=gemini-2.5-pro` for higher quality at higher cost
- The agent will flag skill gaps — use these to decide what to learn or how to frame existing skills

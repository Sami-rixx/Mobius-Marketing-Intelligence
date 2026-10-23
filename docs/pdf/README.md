# docs/pdf/ — Blueprint v2.0 (authoritative sources)

The PDFs in this folder are the source of truth for “The Inevitable Engine”:

| PDF | Markdown companion |
|---|---|
| `00-vision.pdf` | `docs/00-vision.md` |
| `01-architecture.pdf` | `docs/01-architecture.md` |
| `02-agent-contracts.pdf` | `docs/02-agent-contracts.md` |
| `03-content-schema.pdf` | `docs/03-content-schema.md` |
| `04-cadence.pdf` | `docs/04-cadence.md` |
| `05-learning-loop.pdf` | `docs/05-learning-loop.md` |
| `06-limits.pdf` | `docs/06-limits.md` |
| `AGENTS.pdf` | `AGENTS.md` (repository root) |

If a Markdown copy and its PDF disagree, the PDF wins and the Markdown file is a defect to
fix in the same pull request.

> Moved from `Docs/` to `docs/pdf/` so the repository does not contain two paths that differ
> only by case (`Docs/` vs `docs/`); that breaks checkouts on macOS and Windows. Content is
> unchanged.

Status: Milestone M0 implemented (see `docs/07-implementation-notes.md`). The first live run
is a supervised pilot; nothing is published automatically.

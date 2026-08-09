<!-- File-Version: 1.0.0 -->
# Final architecture and code-quality audit

Date: 2026-08-09

## Scope

Reviewed production and test structure, module sizes, responsibility boundaries,
entry points, naming, dead-code indicators, maintenance comments, configuration,
documentation alignment, static checks, test coverage, and current Git state.

Commands included:

```bash
find src tests -name '*.py' -type f -print0 | xargs -0 wc -l
rg -n 'TODO|FIXME|HACK|XXX|NotImplemented|pass' src tests
.venv/bin/python -m vulture src --min-confidence 80
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q --cov=src --cov-report=term-missing
```

## Conclusion

The repository is presentable for engineering review after the current working
changes are assembled into a coherent commit. The production flow has clear
boundaries between market classification, intelligence classification,
relevance, scoring, matching, strategy, portfolio risk, and paper-trading
persistence. The test suite exercises the important decision boundaries and
currently reports 81% aggregate coverage.

No high-confidence dead production symbols, unresolved TODO comments, circular
imports, or release claims remain. A stale versioned HTTP User-Agent was changed
to an unreleased research-client identifier during this audit.

## Ranked findings

### 1. Resolve the working tree before sharing

The repository currently contains many modified, deleted, staged, and untracked
project files from the review work. This is not a code defect, but sharing the
repository in that state would obscure the intended result. Review the complete
diff and create one or more coherent commits only when explicitly ready.

### 2. Keep historical collection inputs and outputs controlled

Generated collection output is now ignored and previously tracked runtime data
is staged for removal. Frozen selectors, manifests, or research inputs that are
intentionally published should be reviewed and added explicitly rather than
mixed with default runtime output.

### 3. Split the historical dataset module later

`src/historical_dataset.py` is 3,277 lines and contains persistence models,
manifests, checkpoints, provider collectors, selection, validation, replay
adapters, and CLI orchestration. It is the largest maintainability weakness.
Splitting it now would create unnecessary regression risk. When historical work
resumes, separate it along those existing responsibility boundaries while
preserving frozen formats and public imports.

### 4. Expand command-line tests when CLI behavior grows

The main entry point currently has a subprocess smoke test for argument loading,
while its operational branches are exercised mainly through runner and pipeline
tests. This is sufficient for the current small CLI. Add direct CLI tests if
more flags, validation, or output contracts are introduced.

### 5. Consider configuration injection later

`src/config.py` loads `.env` and resolves values during import. This is simple
and adequate for the current application, but a typed configuration object
would improve validation and test isolation if deployment environments multiply.
It is not required before sharing.

## Items that should not be added now

- Live trading or order execution.
- Public-dashboard authentication or deployment infrastructure.
- A broad framework rewrite or dependency-injection system.
- Project releases, tags, or package-version metadata.
- A coverage threshold chosen only to improve a badge or headline number.

The major product-quality work remains leakage-safe historical coverage and
probability calibration. Those are correctly documented as limitations and do
not prevent the repository from demonstrating its present engineering scope.

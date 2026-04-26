# seasonality

Calendar-effect research framework based on `notebooks/03_seasonality.ipynb`.

```text
scripts/analyze.py
  -> src/data/yahoo.py
  -> src/research/effects.py
```

## Usage

```bash
cd seasonality
uv sync
uv run python scripts/analyze.py
```

## Research Scope

- month-of-year effect
- day-of-week effect
- turn-of-month effect
- sell-in-May seasonal split
- simple statistical summaries for daily returns


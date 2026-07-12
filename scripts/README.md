# Financial scoring pipeline

This pipeline recalculates the 18-sub-industry quadrant from public financial statements.

## Inputs

- `config/company_universe.csv`: company code, name and sub-industry mapping.
- `config/growth_inputs.csv`: verifiable three-year company or market CAGR. Blank values remain N/A.

## Run in a network-enabled environment

```powershell
python scripts/financial_scoring_pipeline.py --year 114 --season 4
```

`--year` is the ROC fiscal year (`114` = 2025). The default request delay is 1.5 seconds. Responses are cached under `data/cache`; subsequent runs are reproducible and lighter on MOPS.

Offline rerun after the cache has been populated:

```powershell
python scripts/financial_scoring_pipeline.py --year 114 --season 4 --offline
```

## Outputs

- `data/output/company_financial_metrics.csv`
- `data/output/subindustry_scores.csv`
- `data/output/subindustry_scores.json`
- `data/output/evidence_gaps.csv`

The script does not impute missing figures. It calculates:

- Profitability = gross profit / revenue
- Investment Demand = CapEx / revenue
- Operating Demand = (accounts receivable + inventory - accounts payable) / revenue
- Growth Visibility = user-verified three-year CAGR input

Each raw metric is converted to a 1–5 cross-sectional quintile score. X is the mean of Profitability and Growth Visibility; Y is the mean of Investment and Operating Demand; Overall gives each of the four indicators 25% weight.

Before production use, review MOPS account-label aliases and validate every extracted value against the cited filing. Website scores should only be replaced after the Evidence Gap report has been reviewed.

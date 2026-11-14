# Polars lazy scans over a pinned dataset revision

The trajectory parquet is 2.08 GB, almost all of it the `trajectory` column. We download it once at a pinned Hugging Face revision and scan it lazily with polars. Each query reads only the columns it needs, and full trajectories are read only for sampled rows. Summary statistics over all 67,074 rows then run in seconds and fit in a few hundred MB of memory. Pinning the revision means a dataset update cannot silently change the reported numbers.

## Considered options

- pandas: loads whole columns into memory and has no lazy query plan.
- DuckDB: equally good at this. Polars wins because the rest of the analysis is dataframe code, so one library covers both.
- Streaming from the Hub on every run: no download, but results would depend on the network and on whatever revision is current.

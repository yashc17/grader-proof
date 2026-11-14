# Pydantic v2 for data models

Trajectories, labels, LLM-judge outputs and task metadata cross a boundary where the data can be wrong: JSONL files written by hand, model responses, and dataset rows. Pydantic validates at that boundary and gives clear errors. Dataclasses would need hand-written parsing and checks for the same result. Models are frozen. Bulk analysis stays in polars dataframes, and pydantic is used only at the edges, where a single record is read or written.

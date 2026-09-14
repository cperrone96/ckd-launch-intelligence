from pathlib import Path


SQL = (Path(__file__).parents[2] / "sql" / "marts" / "mart_synpuf_journeys.sql").read_text()


def test_sql_persists_all_synthetic_analytics_outputs() -> None:
    assert "analytics_synthetic.mart_journeys" in SQL
    assert "analytics_synthetic.mart_journey_summaries" in SQL
    assert "analytics_synthetic.mart_journey_survival" in SQL
    assert "mart_journey_survival_metadata" in SQL


def test_sql_contract_filters_to_public_synthetic_and_first_target() -> None:
    assert "CAST(evidence_type AS VARCHAR) = 'public_synthetic'" in SQL
    assert "first_target_position" in SQL
    assert "ORDER BY event_date, event_through_date, claim_id" in SQL
    assert "FROM analytics_observed" not in SQL

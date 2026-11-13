from datetime import datetime

from graphiti_core.search.search_filters import ComparisonOperator as Op
from graphiti_core.search.search_filters import DateFilter, SearchFilters


def temporal_filter(valid_at=None, known_at=None):
    fields = {}
    for value, start, end in (
        (valid_at, "valid_at", "invalid_at"),
        (known_at, "created_at", "expired_at"),
    ):
        if value:
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None:
                raise ValueError("Datas devem incluir timezone")
            fields[start] = [[DateFilter(date=instant, comparison_operator=Op.less_than_equal)]]
            fields[end] = [
                [DateFilter(comparison_operator=Op.is_null)],
                [DateFilter(date=instant, comparison_operator=Op.greater_than)],
            ]
    return SearchFilters(**fields)

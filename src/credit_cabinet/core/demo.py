from datetime import date
from uuid import UUID

CALCULATION_DATE = date(2026, 10, 1)
FINANCIAL_MONTHS = tuple(date(2026, month, 1) for month in range(4, 10))
FINANCIAL_AS_OF_DATE = date(2026, 9, 30)
DEMO_NAMESPACE = UUID("9079ad9b-f2d1-4574-9f71-8a8f1945646a")

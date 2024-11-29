from enum import Enum, auto


class PaymentStatus(Enum):
    def _generate_next_value_(name, start, count, last_values):
        return name

    PENDING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELED = auto()

    # PENDING = "PENDING"
    # COMPLETED = "COMPLETED"
    # FAILED = "FAILED"
    # CANCELED = "CANCELED"

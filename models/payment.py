from datetime import datetime
from sqlmodel import Field, SQLModel

from enums.payment_type import PaymentStatus


class Payment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    space_id: str
    space_name: str
    user_id: str
    user_name: str
    tid: str
    order_number: str
    p_status: PaymentStatus
    amount: int
    payment_method: str
    payment_date: datetime = Field(default_factory=datetime.now)
